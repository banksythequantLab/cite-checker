"""
Check every citation in a brief against the real opinion.

For each citation the brief makes, three independent, non-AI checks:
  EXISTS      does CourtListener resolve the cite to a real case?
  SAME CASE   is the resolved case the one the brief names? (a cite can land on
              a real page that belongs to a different case -- Avianca's fakes did)
  VERBATIM    is each passage the brief quotes actually in the opinion, word
              for word (whitespace-insensitive)?

Statuses:
  VERIFIED    exists, right case, every quote found
  MISQUOTE    exists, right case, but a quoted passage is not in the opinion
  WRONG_CASE  the cite resolves to a different case than the brief names
  NOT_FOUND   CourtListener has no case at that citation
  AMBIGUOUS   the cite matches several cases
  UNQUOTED    exists, right case, nothing quoted to check
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import courtlistener as CL
import extract as EX
import spans


def _norm_name(s: str | None) -> set[str]:
    s = (s or "").lower()
    s = re.sub(r"\b(inc|llc|corp|co|ltd|lp|llp|plc|sa|ag|nv|bv|the|of|and|&|v|vs|in re|matter of|et al)\b\.?", " ", s)
    return {w for w in re.findall(r"[a-z][a-z]{2,}", s)}


def _tok_match(x: str, y: str) -> bool:
    """Legal citations abbreviate: Corp./Corporation, Sec./Securities,
    Litig./Litigation, Ass'n/Association. Treat a token as matching when one
    is a prefix of the other (both at least 3 chars)."""
    return x == y or (len(x) >= 3 and len(y) >= 3 and (x.startswith(y) or y.startswith(x)))


def names_match(brief_name: str | None, cl_name: str | None) -> bool:
    a, b = _norm_name(brief_name), _norm_name(cl_name)
    if not a or not b:
        return True          # nothing to compare -> don't accuse
    hits = sum(1 for x in a if any(_tok_match(x, y) for y in b))
    return hits / max(1, min(len(a), len(b))) >= 0.5


@dataclass
class Finding:
    citation: str
    case_name_in_brief: str | None
    status: str
    cl_case_name: str | None = None
    cl_url: str | None = None
    quotes: list[dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def check_brief(text: str) -> list[Finding]:
    cites = EX.extract(text)
    if not cites:
        return []
    # one lookup for the whole brief; map results by "vol rep page"
    results = CL.lookup(text)
    by_key: dict[str, dict] = {}
    for r in results:
        key = f"{r.get('volume')} {r.get('reporter')} {r.get('page')}"
        by_key[re.sub(r"\s+", " ", key)] = r

    findings: list[Finding] = []
    for c in cites:
        r = by_key.get(c.key) or by_key.get(c.key.replace(" ", ""))
        if r is None:
            # CourtListener did not even see this as a citation -> treat as not found
            findings.append(Finding(c.raw, c.case_name, "NOT_FOUND",
                                    note="citation not recognised by CourtListener"))
            continue
        st = r.get("status")
        clusters = r.get("clusters") or []
        if st == 404 or not clusters:
            findings.append(Finding(c.raw, c.case_name, "NOT_FOUND",
                                    note=r.get("error_message") or "no case at this citation"))
            continue
        if st == 300 or len(clusters) > 1:
            findings.append(Finding(c.raw, c.case_name, "AMBIGUOUS",
                                    note=f"{len(clusters)} candidate cases"))
            continue
        cl = clusters[0]
        cl_name = cl.get("case_name")
        url = CL.BASE + (cl.get("absolute_url") or "")
        if not names_match(c.case_name, cl_name):
            findings.append(Finding(c.raw, c.case_name, "WRONG_CASE", cl_name, url,
                                    note="citation resolves to a different case than the brief names"))
            continue
        if not c.quotes:
            findings.append(Finding(c.raw, c.case_name, "UNQUOTED", cl_name, url))
            continue
        try:
            opinion, _meta = CL.opinion_text(cl["id"])
        except CL.CLError as e:
            findings.append(Finding(c.raw, c.case_name, "UNQUOTED", cl_name, url,
                                    note=f"could not fetch opinion text: {e}"))
            continue
        checks = [spans.verify(opinion, q) for q in c.quotes]
        allok = all(ch["verified"] for ch in checks)
        findings.append(Finding(c.raw, c.case_name,
                                "VERIFIED" if allok else "MISQUOTE", cl_name, url,
                                quotes=checks,
                                note="" if allok else "a quoted passage is not in the opinion"))
    return findings
