"""
Citation extraction from a brief. Deterministic regex over the reporters a
litigator actually cites. The model is NOT used to find citations -- a regex
cannot hallucinate a case. The model's only job (later) is to pair each
citation with the quoted proposition the brief attributes to it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# volume  reporter  page   -- reporters commonly seen in federal + NY practice
REPORTERS = (
    r"U\.S\.|S\. ?Ct\.|L\. ?Ed\. ?2d|"
    r"F\.4th|F\.3d|F\.2d|F\.|F\. ?Supp\. ?3d|F\. ?Supp\. ?2d|F\. ?Supp\.|F\.R\.D\.|"
    r"B\.R\.|Fed\. ?Appx\.|F\. ?App'x|"
    r"N\.Y\.3d|N\.Y\.2d|N\.Y\.|A\.D\.3d|A\.D\.2d|N\.Y\.S\.3d|N\.Y\.S\.2d|N\.E\.3d|N\.E\.2d|"
    r"WL"
)
CITE_RE = re.compile(
    rf"(?P<vol>\d{{1,4}})\s+(?P<rep>{REPORTERS})\s+(?P<page>\d{{1,7}})"
    r"(?:,\s*(?P<pin>\d{1,6}(?:-\d{1,6})?))?"
    r"(?:\s*\((?P<court>[^()]*?)\s*(?P<year>(?:18|19|20)\d{2})\))?"
)
# case name immediately before the cite: "Foo v. Bar," or "In re Foo,"
NAME_RE = re.compile(
    r"((?:In re |Matter of |Ex parte )[A-Z][A-Za-z0-9.'&,\- ]{1,80}?"
    r"|[A-Z][A-Za-z0-9.'&,\- ]{1,80}?\s+v\.\s+[A-Z][A-Za-z0-9.'&,\- ]{1,80}?)\s*,\s*$"
)
_LOWER_WORD = re.compile(r"\b[a-z][a-z]*\b")


def _trim_name(name: str) -> str:
    """Drop leading prose: 'The Second Circuit has applied this in Ashcroft v.
    Iqbal' -> 'Ashcroft v. Iqbal'. Case names are capitalised runs; cut after
    the last lowercase word that precedes the party names (but keep 'v.',
    'In re', 'Matter of', 'of', '&' etc. inside the name)."""
    head = name.split(" v. ")[0] if " v. " in name else name
    keep_lower = {"of", "the", "and", "for", "re", "ex", "parte", "on", "de", "la", "du"}
    cut = 0
    for m in _LOWER_WORD.finditer(head):
        if m.group(0) not in keep_lower:
            cut = m.end()
    if cut:
        name = name[cut:]
    return name.strip(" .,;:")


@dataclass
class Citation:
    raw: str
    case_name: str | None
    volume: str
    reporter: str
    page: str
    pin: str | None
    court: str | None
    year: str | None
    start: int
    end: int
    quotes: list[str] = field(default_factory=list)   # quoted text near the cite

    @property
    def key(self) -> str:
        return f"{self.volume} {self.reporter} {self.page}"


def _nearby_quotes(text: str, start: int, lo: int) -> list[str]:
    """Quoted passages between the previous citation and this one -- a brief
    quotes a case then cites it, so the quote belongs to the NEXT cite."""
    chunk = text[lo:start]
    qs = re.findall(r"[\"“]([^\"”]{20,600})[\"”]", chunk)
    return [q.strip() for q in qs]


def _trailing_parenthetical(text: str, end: int) -> tuple[list[str], int]:
    """Bluebook explanatory parenthetical right after a cite --
    `550 U.S. 544 (2007) ("plausible on its face")` -- belongs to THIS cite,
    not the next one. Returns (quotes, end of the parenthetical) or ([], end).
    Balanced-paren scan, bounded, so `(quoting Foo (2d Cir. 2001))` is one unit;
    consecutive parentheticals `(quoting X) ("...")` are all consumed."""
    quotes: list[str] = []
    while True:
        m = re.match(r"\s*\(", text[end:end + 8])
        if not m:
            return quotes, end
        i = end + m.end()
        depth = 1
        limit = min(len(text), i + 900)
        while i < limit and depth:
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        if depth:
            return quotes, end
        inner = text[end + m.end():i - 1]
        quotes += [q.strip() for q in re.findall(r"[\"“]([^\"”]{20,600})[\"”]", inner)]
        end = i


def extract(text: str) -> list[Citation]:
    out: list[Citation] = []
    by_key: dict[tuple, Citation] = {}
    prev_end = 0
    for m in CITE_RE.finditer(text):
        key = (m.group("vol"), re.sub(r"\s+", " ", m.group("rep")), m.group("page"))
        # a cite nested inside a consumed parenthetical ("(quoting X, 1 F.3d 1)")
        # is still extracted and checked; it just inherits no quotes from
        # before it (prev_end is already past it, so the chunk is empty).
        trailing, after = _trailing_parenthetical(text, m.end())
        if key in by_key:
            # the same case cited again, possibly with a NEW quote attached --
            # a brief's second cite of Twombly can carry a fabricated quote the
            # first did not. Merge the quotes; never drop an occurrence.
            by_key[key].quotes.extend(_nearby_quotes(text, m.start(), prev_end) + trailing)
            prev_end = after
            continue
        before = text[max(0, m.start() - 160):m.start()]
        nm = NAME_RE.search(before)
        c = Citation(
            raw=m.group(0).strip(),
            case_name=_trim_name(nm.group(1)) if nm else None,
            volume=m.group("vol"), reporter=re.sub(r"\s+", " ", m.group("rep")),
            page=m.group("page"), pin=m.group("pin"),
            court=(m.group("court") or "").strip() or None, year=m.group("year"),
            start=m.start(), end=m.end(),
            quotes=_nearby_quotes(text, m.start(), prev_end) + trailing,
        )
        by_key[key] = c
        out.append(c)
        prev_end = max(prev_end, after)
    return out
