"""Verify a quote appears verbatim in an opinion's text.

"Verbatim" tolerates the things that are not words of the opinion:
  * whitespace differences (line wraps, double spaces)
  * curly vs straight quotes and apostrophes, en/em dashes vs hyphens
  * CourtListener's star pagination markers ("*46") and bare footnote
    numbers ("relief. 5 Here") that sit inside the running text
The match is otherwise exact, and the returned offsets point into the
ORIGINAL document so the matched span can be shown as it appears there.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
           " ": " "}
# a star-page marker (*46, *1339) or a bare footnote number (1-3 digits) between words
_NOISE = re.compile(r"(?<=\s)(\*\d{1,5}|\d{1,3})(?=\s)")


def _fold(ch: str) -> str:
    return _QUOTES.get(ch, ch)


def _norm(t: str, drop_noise: bool):
    """Collapse whitespace, fold punctuation, optionally drop page/footnote
    markers. Returns (normalized text, map from normalized index -> original index)."""
    if drop_noise:
        # blank out noise tokens in place so indices stay aligned
        t = _NOISE.sub(lambda m: " " * len(m.group(0)), t)
    out, mp, prev = [], [], False
    for i, ch in enumerate(t):
        if ch.isspace():
            if prev:
                continue
            out.append(" "); mp.append(i); prev = True
        else:
            out.append(_fold(ch)); mp.append(i); prev = False
    return "".join(out), mp


def _normq(q: str) -> str:
    return _WS.sub(" ", "".join(_fold(c) for c in q)).strip()


def verify(doc: str, quote: str):
    q = (quote or "").strip()
    if len(q) < 10:
        return {"verified": False, "reason": "too short", "quote": quote}
    nq = _normq(q)
    for drop_noise, how in ((False, "verified exact span"),
                            (True, "verified exact span (page/footnote markers skipped)")):
        nd, mp = _norm(doc, drop_noise)
        pos = nd.find(nq)
        if pos != -1:
            s, e = mp[pos], mp[pos + len(nq) - 1] + 1
            return {"verified": True, "reason": how, "quote": quote,
                    "start": s, "end": e, "matched": doc[s:e]}
    return {"verified": False, "reason": "not found verbatim", "quote": quote}
