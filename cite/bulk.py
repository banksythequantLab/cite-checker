"""Local CourtListener index built from the free bulk dumps.

    python3 cite/bulk.py build-index  [--date 2026-09-30] [--out /data/cl.db]
    python3 cite/bulk.py build-text   [--date 2026-09-30] [--out /data/cl.db]

build-index streams citations-*.csv.bz2 (0.13 GB) and opinion-clusters-*.csv.bz2
(2.5 GB) straight from S3 into SQLite: every reporter citation -> cluster, and
every cluster -> case name / date / court. That replaces the citation-lookup
API call, which is what the free tier's 125/day quota throttles.

build-text streams opinions-*.csv.bz2 (55 GB) into the same DB: per-opinion
plain text (or stripped HTML), zstd-compressed if zstandard is installed.
That replaces the per-opinion fetch. Hours on a small VM; needs block storage.

Nothing is downloaded to disk uncompressed -- bz2 is decoded on the fly.
"""
from __future__ import annotations

import argparse
import bz2
import csv
import html as _html
import io
import os
import re
import sqlite3
import sys
import time

import httpx

S3 = "https://com-courtlistener-storage.s3-us-west-2.amazonaws.com/bulk-data"
csv.field_size_limit(1 << 30)


def stream_csv(name: str, date: str):
    """Yield dict rows from an S3 bz2 CSV without ever writing it to disk."""
    url = f"{S3}/{name}-{date}.csv.bz2"

    def lines():
        dec = bz2.BZ2Decompressor()
        buf = ""; done = 0; t0 = time.time(); mark = 0
        with httpx.stream("GET", url, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            for chunk in r.iter_bytes(1 << 20):
                done += len(chunk)
                parts = (buf + dec.decompress(chunk).decode("utf-8", "replace")).split("\n")
                buf = parts.pop()            # partial last line waits for the next chunk
                for line in parts:
                    yield line + "\n"
                if done - mark >= (256 << 20):
                    mark = done
                    rate = done / max(time.time() - t0, 1) / 1e6
                    print(f"  {name}: {done/1e9:.2f}/{total/1e9:.2f} GB  {rate:.1f} MB/s",
                          file=sys.stderr, flush=True)
        if buf:
            yield buf

    # a multi-line quoted field simply pulls more lines; the generator blocks
    # on the network until they arrive, so the reader never sees a torn record
    yield from csv.DictReader(lines(), quotechar='"', escapechar="\\", doublequote=False,
                              strict=True)


def _db(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.executescript("""
    PRAGMA journal_mode=WAL; PRAGMA synchronous=OFF;
    CREATE TABLE IF NOT EXISTS citations(volume TEXT, reporter TEXT, page TEXT,
        cluster_id INTEGER, type INTEGER);
    CREATE TABLE IF NOT EXISTS clusters(id INTEGER PRIMARY KEY, case_name TEXT,
        case_name_full TEXT, date_filed TEXT, slug TEXT, precedential_status TEXT);
    CREATE TABLE IF NOT EXISTS opinions(id INTEGER PRIMARY KEY, cluster_id INTEGER,
        type TEXT, text BLOB, codec TEXT);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    return c


def build_index(date: str, out: str):
    c = _db(out)
    n = 0
    c.execute("DELETE FROM citations")
    for row in stream_csv("citations", date):
        c.execute("INSERT INTO citations VALUES(?,?,?,?,?)",
                  (row["volume"], row["reporter"], row["page"], int(row["cluster_id"]),
                   int(row["type"] or 0)))
        n += 1
        if n % 100000 == 0: c.commit()
    c.commit()
    c.execute("CREATE INDEX IF NOT EXISTS ix_cite ON citations(volume, page)")
    print(f"citations: {n:,}", file=sys.stderr)
    n = 0
    for row in stream_csv("opinion-clusters", date):
        c.execute("INSERT OR REPLACE INTO clusters VALUES(?,?,?,?,?,?)",
                  (int(row["id"]), row["case_name"], row["case_name_full"], row["date_filed"],
                   row["slug"], row["precedential_status"]))
        n += 1
        if n % 50000 == 0: c.commit()
    c.commit()
    c.execute("INSERT OR REPLACE INTO meta VALUES('index_date',?)", (date,))
    c.commit()
    c.execute("PRAGMA journal_mode=DELETE")   # so a read-only mount can open it
    print(f"clusters: {n:,}  ->  {out}", file=sys.stderr)


def _strip(h: str) -> str:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def build_text(date: str, out: str):
    try:
        import zstandard as zstd
        cx = zstd.ZstdCompressor(level=6); codec = "zstd"
    except ImportError:
        cx = None; codec = "raw"
    c = _db(out)
    n = kept = 0
    for row in stream_csv("opinions", date):
        n += 1
        text = row.get("plain_text") or ""
        if len(text.strip()) < 200:
            for col in ("html_with_citations", "html", "xml_harvard", "html_lawbox",
                        "html_columbia", "html_anon_2020"):
                if row.get(col) and len(row[col]) > 200:
                    text = _strip(row[col]); break
        if not text.strip():
            continue
        blob = cx.compress(text.encode()) if cx else text.encode()
        c.execute("INSERT OR REPLACE INTO opinions VALUES(?,?,?,?,?)",
                  (int(row["id"]), int(row["cluster_id"]), row["type"], blob, codec))
        kept += 1
        if n % 20000 == 0: c.commit()
    c.commit()
    c.execute("INSERT OR REPLACE INTO meta VALUES('text_date',?)", (date,))
    c.commit()
    c.execute("PRAGMA journal_mode=DELETE")
    print(f"opinions: {n:,} rows, {kept:,} with text  ->  {out}", file=sys.stderr)


# ---- query side, used by verify.py when CITE_BULK_DB is set -----------------
_Q = None


def available() -> bool:
    p = os.environ.get("CITE_BULK_DB")
    return bool(p and os.path.exists(p))


def _q():
    global _Q
    if _Q is None:
        _Q = sqlite3.connect(f"file:{os.environ['CITE_BULK_DB']}?mode=ro", uri=True,
                             check_same_thread=False)
    return _Q


def lookup_local(vol: str, rep: str, page: str) -> list[dict]:
    """Return clusters for a cite, shaped like a citation-lookup API cluster."""
    rows = _q().execute(
        "SELECT c.id, c.case_name, c.case_name_full, c.date_filed, c.slug "
        "FROM citations x JOIN clusters c ON c.id=x.cluster_id "
        "WHERE x.volume=? AND x.page=? AND replace(x.reporter,' ','')=?",
        (vol, page, rep.replace(" ", ""))).fetchall()
    return [{"id": r[0], "case_name": r[1], "case_name_full": r[2], "date_filed": r[3],
             "absolute_url": f"/opinion/{r[0]}/{r[4]}/", "sub_opinions": []} for r in rows]


def opinion_text_local(cluster_id: int) -> str | None:
    rows = _q().execute("SELECT text, codec FROM opinions WHERE cluster_id=? ORDER BY "
                        "CASE type WHEN '010combined' THEN 0 WHEN '020lead' THEN 1 ELSE 2 END",
                        (cluster_id,)).fetchall()
    if not rows:
        return None
    parts = []
    for blob, codec in rows:
        if codec == "zstd":
            import zstandard as zstd
            parts.append(zstd.ZstdDecompressor().decompress(blob).decode())
        else:
            parts.append(bytes(blob).decode())
    return "\n\n".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build-index", "build-text"])
    ap.add_argument("--date", default="2026-09-30")
    ap.add_argument("--out", default=os.environ.get("CITE_BULK_DB", "cl.db"))
    a = ap.parse_args()
    (build_index if a.cmd == "build-index" else build_text)(a.date, a.out)
