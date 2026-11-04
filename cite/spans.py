"""Verify a model-cited quote appears verbatim (whitespace-insensitive) in text."""
from __future__ import annotations
import re
_WS = re.compile(r"\s+")
def _norm(t):
    out, mp, prev = [], [], False
    for i, ch in enumerate(t):
        if ch.isspace():
            if prev: continue
            out.append(" "); mp.append(i); prev = True
        else:
            out.append(ch); mp.append(i); prev = False
    return "".join(out), mp
def verify(doc: str, quote: str):
    q = (quote or "").strip()
    if len(q) < 10: return {"verified": False, "reason": "too short", "quote": quote}
    nd, mp = _norm(doc); nq = _WS.sub(" ", q).strip()
    pos = nd.find(nq)
    if pos == -1: return {"verified": False, "reason": "not found verbatim", "quote": quote}
    s, e = mp[pos], mp[pos+len(nq)-1]+1
    return {"verified": True, "reason": "verified exact span", "quote": quote,
            "start": s, "end": e, "matched": doc[s:e]}
