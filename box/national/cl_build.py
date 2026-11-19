#!/opt/banksy/lex/venv/bin/python
# -*- coding: utf-8 -*-
"""cl_build.py - build the nationwide CourtListener files that cl_national.py reads, from the public bulk dumps.

Reads ONE decompressed CourtListener CSV on stdin (the dumps are PostgreSQL CSV: quote ", escape backslash) and
writes into a SQLite file. Standard library only (zstd from Python 3.14's `compression`).

  bzip2 -dc citations-DATE.csv.bz2        | cl_build.py citations --out new/cl.db
  bzip2 -dc opinion-clusters-DATE.csv.bz2 | cl_build.py clusters  --out new/cl.db --date DATE
  bzip2 -dc opinions-DATE.csv.bz2         | cl_build.py text      --out new/cl-text.db --date DATE [--workers N]

`clusters` writes meta.index_date and `text` writes meta.text_date + text_rows only when the whole stream was read
cleanly, so a torn or truncated input can never be mistaken for a finished build. national_refresh.sh drives it."""
import argparse, csv, html, re, sqlite3, sys, time
from compression import zstd

csv.field_size_limit(1 << 30)
TEXT_COLS = ("html_with_citations", "html", "xml_harvard", "html_lawbox", "html_columbia", "html_anon_2020")

def rows():
    return csv.DictReader(sys.stdin, quotechar='"', escapechar="\\", doublequote=False, strict=True)

def db(path, schema):
    c = sqlite3.connect(path); c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=OFF"); c.executescript(schema); return c

INDEX_SCHEMA = """
create table if not exists citations(volume TEXT, reporter TEXT, page TEXT, cluster_id INTEGER, type INTEGER);
create table if not exists clusters(id INTEGER PRIMARY KEY, case_name TEXT, case_name_full TEXT, date_filed TEXT, slug TEXT, precedential_status TEXT);
create table if not exists meta(k TEXT PRIMARY KEY, v TEXT);"""
TEXT_SCHEMA = """
create table if not exists opinions(id INTEGER PRIMARY KEY, cluster_id INTEGER, type TEXT, text BLOB, codec TEXT);
create table if not exists meta(k TEXT PRIMARY KEY, v TEXT);"""

def log(msg): print(msg, file=sys.stderr, flush=True)

def citations(out):
    c = db(out, INDEX_SCHEMA); c.execute("delete from citations"); n = 0
    for r in rows():
        c.execute("insert into citations values(?,?,?,?,?)", (r["volume"], r["reporter"], r["page"], int(r["cluster_id"]), int(r["type"] or 0))); n += 1
        if n % 200000 == 0: c.commit()
        if n % 2000000 == 0: log("  citations: %d" % n)
    c.commit(); c.execute("create index if not exists ix_cite on citations(volume, page)")
    c.execute("insert or replace into meta values('citations', ?)", (str(n),)); c.commit(); log("citations: %d" % n)

def clusters(out, date):
    c = db(out, INDEX_SCHEMA); n = 0
    for r in rows():
        c.execute("insert or replace into clusters values(?,?,?,?,?,?)", (int(r["id"]), r["case_name"], r["case_name_full"], r["date_filed"], r["slug"], r["precedential_status"])); n += 1
        if n % 100000 == 0: c.commit()
        if n % 2000000 == 0: log("  clusters: %d" % n)
    c.commit()
    c.execute("insert or replace into meta values('clusters', ?)", (str(n),))
    c.execute("insert or replace into meta values('index_date', ?)", (date,)); c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.execute("PRAGMA journal_mode=DELETE"); log("clusters: %d" % n)

def _strip(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()

def _prep(item):
    oid, cid, typ, raw, is_html = item
    t = _strip(raw) if is_html else raw
    return (oid, cid, typ, zstd.compress(t.encode(), 3), "zstd") if t.strip() else None

def text(out, date, workers):
    import multiprocessing as mp
    c = db(out, TEXT_SCHEMA); n = kept = 0; t0 = time.time(); pool = mp.Pool(workers)
    def items():
        nonlocal n
        for r in rows():
            n += 1
            p = r.get("plain_text") or ""
            if len(p.strip()) >= 200: yield (int(r["id"]), int(r["cluster_id"]), r["type"], p, False); continue
            for col in TEXT_COLS:
                if r.get(col) and len(r[col]) > 200: yield (int(r["id"]), int(r["cluster_id"]), r["type"], r[col], True); break
    def flush(batch):
        nonlocal kept
        for res in pool.map(_prep, batch, chunksize=32):          # bounded batches: memory stays flat
            if res: c.execute("insert or replace into opinions values(?,?,?,?,?)", res); kept += 1
        c.commit()
    batch = []
    for it in items():
        batch.append(it)
        if len(batch) >= 512:
            flush(batch); batch = []
            if n % 200000 < 512: log("  opinions: %d rows, %d stored, %.0f rows/s" % (n, kept, n / max(time.time() - t0, 1)))
    if batch: flush(batch)
    pool.close(); pool.join()
    c.execute("create index if not exists ix_op_cluster on opinions(cluster_id)")
    total = c.execute("select count(*) from opinions").fetchone()[0]
    c.execute("insert or replace into meta values('text_rows', ?)", (str(total),))
    c.execute("insert or replace into meta values('text_date', ?)", (date,)); c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)"); c.execute("PRAGMA journal_mode=DELETE"); log("opinions: %d rows, %d with text" % (n, total))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["citations", "clusters", "text"])
    ap.add_argument("--out", required=True); ap.add_argument("--date", default=""); ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    try:
        if a.cmd == "citations": citations(a.out)
        elif a.cmd == "clusters": clusters(a.out, a.date)
        else: text(a.out, a.date, a.workers)
    except csv.Error as e:
        log("STREAM TORN: %s - build NOT marked complete" % e); sys.exit(3)
