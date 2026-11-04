"""
CourtListener (Free Law Project) API v4 client. Needs a free token.

Two calls do the real work:
  citation-lookup  POST text -> every citation found in it, each with a status
                   (200 found / 404 not found / 300 ambiguous) and the cluster
                   it resolves to. This is CourtListener's own judgment of
                   whether a citation EXISTS -- not ours, not a model's.
  opinions/{id}    the opinion's text, used to check quotes verbatim.
"""
from __future__ import annotations

import html
import os
import re

import httpx

BASE = "https://www.courtlistener.com"


class CLError(RuntimeError):
    pass


def _token() -> str:
    t = os.environ.get("COURTLISTENER_TOKEN", "").strip()
    if not t:
        raise CLError("COURTLISTENER_TOKEN unset -- get a free token at "
                      "https://www.courtlistener.com/profile/api/")
    return t


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=40,
                        headers={"Authorization": f"Token {_token()}",
                                 "User-Agent": "cite-checker/0.1"})


def lookup(text: str) -> list[dict]:
    """Resolve every citation in `text`. Returns CourtListener's list."""
    with _client() as c:
        r = c.post("/api/rest/v4/citation-lookup/", data={"text": text[:60000]})
        if r.status_code != 200:
            raise CLError(f"citation-lookup HTTP {r.status_code}: {r.text[:200]}")
        return r.json()


def _strip(h: str) -> str:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def opinion_text(cluster_id: int) -> tuple[str, dict]:
    """Full text of a cluster's opinion(s) + the cluster's metadata."""
    with _client() as c:
        r = c.get(f"/api/rest/v4/clusters/{cluster_id}/")
        if r.status_code != 200:
            raise CLError(f"cluster {cluster_id} HTTP {r.status_code}")
        cl = r.json()
        texts = []
        for url in cl.get("sub_opinions", []):
            oid = str(url).rstrip("/").split("/")[-1]
            o = c.get(f"/api/rest/v4/opinions/{oid}/")
            if o.status_code != 200:
                continue
            od = o.json()
            t = (od.get("plain_text") or "").strip()
            if not t:
                t = _strip(od.get("html_with_citations") or od.get("html") or
                           od.get("html_lawbox") or od.get("html_columbia") or
                           od.get("xml_harvard") or "")
            if t:
                texts.append(t)
        meta = {"case_name": cl.get("case_name"), "date_filed": cl.get("date_filed"),
                "url": BASE + (cl.get("absolute_url") or ""),
                "citations": [f"{x.get('volume')} {x.get('reporter')} {x.get('page')}"
                              for x in cl.get("citations", [])]}
        return "\n\n".join(texts), meta
