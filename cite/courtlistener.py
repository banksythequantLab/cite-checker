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
import time

import httpx

BASE = "https://www.courtlistener.com"
_PACE_S = 1.2            # polite gap between requests; the free tier rate-limits bursts
_last_call = 0.0
_cache: dict[int, tuple[str, dict]] = {}

# The free tier allows 125 requests/day on cluster/opinion endpoints. Opinions
# are immutable, so every fetched opinion is cached on disk permanently and a
# brief that cites a case we have seen costs zero requests for it. (A product
# would load CourtListener's free bulk opinion dumps onto a Vultr block-storage
# volume and never call the API for text at all.)
import json as _json
import sqlite3 as _sqlite
_DB = os.environ.get("CITE_CACHE", os.path.expanduser("~/.cite_cache.db"))


def _db():
    c = _sqlite.connect(_DB)
    c.execute("CREATE TABLE IF NOT EXISTS opinions(cluster_id INTEGER PRIMARY KEY, "
              "text TEXT, meta TEXT, fetched_at TEXT)")
    return c


def _cache_get(cluster_id: int):
    r = _db().execute("SELECT text, meta FROM opinions WHERE cluster_id=?",
                      (cluster_id,)).fetchone()
    return (r[0], _json.loads(r[1])) if r else None


def _cache_put(cluster_id: int, text: str, meta: dict) -> None:
    c = _db()
    c.execute("INSERT OR REPLACE INTO opinions VALUES(?,?,?,datetime('now'))",
              (cluster_id, text, _json.dumps(meta)))
    c.commit()


def _get(c: httpx.Client, url: str, tries: int = 5) -> httpx.Response:
    """GET with pacing and exponential backoff on 429/5xx. A 429 must never be
    mistaken for 'no text' -- it is retried, and if it still fails we raise."""
    global _last_call
    for i in range(tries):
        wait = _PACE_S - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        r = c.get(url)
        _last_call = time.monotonic()
        if r.status_code == 429:
            ra = r.headers.get("retry-after")
            if ra and ra.isdigit() and int(ra) > 300:
                # the DAILY quota, not a burst: do not sit in a retry loop
                raise CLError(f"CourtListener daily quota exhausted; resets in "
                              f"{int(ra)//3600}h{(int(ra)%3600)//60}m")
            time.sleep(float(ra) if ra and ra.isdigit() else (2 ** i) * 1.5)
            continue
        if r.status_code >= 500:
            time.sleep((2 ** i) * 1.5)
            continue
        return r
    raise CLError(f"{url}: still rate-limited after {tries} tries (HTTP {r.status_code})")


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


def _norm(k: str) -> str:
    return re.sub(r"\s+", " ", str(k)).strip()


def _lk_db():
    c = _db()
    c.execute("CREATE TABLE IF NOT EXISTS lookups(cite TEXT PRIMARY KEY, result TEXT, "
              "fetched_at TEXT)")
    return c


def lookup_cites(cites: list[str]) -> list[dict]:
    """Resolve a list of citation strings ("550 U.S. 544"), serving from the
    cache where possible and POSTing only the unknown ones, in one request.
    Same output shape as lookup(). A 404 (not found) is cached too: the answer
    for a reporter page does not change day to day, and the free tier is
    125 requests/day."""
    want = {_norm(x) for x in cites if x}
    db = _lk_db()
    out, missing = [], []
    import bulk
    local = bulk.available()
    for k in sorted(want):
        if local:
            parts = k.split(" ")
            if len(parts) >= 3:
                cl = bulk.lookup_local(parts[0], " ".join(parts[1:-1]), parts[-1])
                if cl:
                    out.append({"citation": k, "normalized_citations": [k], "status": 200,
                                "clusters": cl, "source": "bulk"})
                    continue
            # not in the local dump: fall through to the API (newer cases, odd reporters)
        row = db.execute("SELECT result FROM lookups WHERE cite=?", (k,)).fetchone()
        (out.append(_json.loads(row[0])) if row else missing.append(k))
    if missing:
        fresh = lookup("\n".join(missing))
        seen = set()
        for r in fresh:
            out.append(r)
            for k in [r.get("citation")] + list(r.get("normalized_citations") or []):
                if k:
                    db.execute("INSERT OR REPLACE INTO lookups VALUES(?,?,datetime('now'))",
                               (_norm(k), _json.dumps(r)))
                    seen.add(_norm(k))
        # a cite CourtListener didn't even echo back: remember that as not-found
        for k in missing:
            if k not in seen:
                nf = {"citation": k, "status": 404, "clusters": [],
                      "error_message": "not recognised by CourtListener"}
                out.append(nf)
                db.execute("INSERT OR REPLACE INTO lookups VALUES(?,?,datetime('now'))",
                           (k, _json.dumps(nf)))
        db.commit()
    return out


def _strip(h: str) -> str:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def opinion_text(cluster_id: int, cluster: dict | None = None) -> tuple[str, dict]:
    """Full text of a cluster's opinion(s) + metadata. Disk-cached forever.
    Pass the cluster dict from citation-lookup when you have it: it already
    carries sub_opinions, which saves the cluster GET (one request per cite).
    Raises CLError rather than ever returning empty text silently."""
    if cluster_id in _cache:
        return _cache[cluster_id]
    hit = _cache_get(cluster_id)
    if hit:
        _cache[cluster_id] = hit
        return hit
    import bulk
    if bulk.available():
        t = bulk.opinion_text_local(cluster_id)
        if t and t.strip():
            _cache[cluster_id] = (t, {"source": "bulk"})
            return _cache[cluster_id]
    with _client() as c:
        if cluster and cluster.get("sub_opinions"):
            cl = cluster
        else:
            r = _get(c, f"/api/rest/v4/clusters/{cluster_id}/")
            if r.status_code != 200:
                raise CLError(f"cluster {cluster_id} HTTP {r.status_code}: {r.text[:120]}")
            cl = r.json()
        texts = []
        for url in cl.get("sub_opinions", []):
            oid = str(url).rstrip("/").split("/")[-1]
            o = _get(c, f"/api/rest/v4/opinions/{oid}/")
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
        full = "\n\n".join(texts)
        if not full.strip():
            raise CLError(f"cluster {cluster_id}: no opinion text available")
        _cache[cluster_id] = (full, meta)
        _cache_put(cluster_id, full, meta)
        return full, meta
