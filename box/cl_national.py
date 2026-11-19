# -*- coding: utf-8 -*-
"""cl_national.py - the nationwide half of the box's citation checker.

Lex (PostgreSQL) holds New York and Second Circuit opinions in full. This module adds a read-only copy of
CourtListener's bulk data for every U.S. court, built for the Legal Cite Checker (cite.nota.lawyer):

  national/cl.db        18.1M reporter citations -> 10.7M case clusters (name, date)        ~3 GB
  national/cl-text.db   10.0M opinion texts, zstd-compressed, indexed by cluster            ~53 GB

cite_check.py asks it two things, only when Lex itself cannot settle a citation:
  lookup(vol, forms, page) -> the case(s) CourtListener files under that reporter citation
  text(cluster_id)         -> the opinion text, so a quotation can be checked against the case itself

Everything is local SQLite opened read-only; nothing leaves the box. If the files are missing every call
returns "nothing", and cite_check.py behaves exactly as it did before. The marker file national/READY
switches it on; it is written only after the data files were copied in full and checked."""
import os, re, sqlite3

DIR = os.environ.get("CL_NATIONAL_DIR", "/opt/banksy/lex/national")
INDEX, TEXT = os.path.join(DIR, "cl.db"), os.path.join(DIR, "cl-text.db")
URL = "https://www.courtlistener.com/opinion/%s/%s/"
_c = {}

try:
    from compression import zstd as _z            # Python 3.14+
    def _unz(b): return _z.decompress(b)
except Exception:                                  # older Pythons: the zstandard wheel
    try:
        import zstandard as _zs
        def _unz(b): return _zs.ZstdDecompressor().decompress(b)
    except Exception:
        _unz = None

def _open(path, key):
    if key not in _c:
        _c[key] = None
        if os.path.exists(path) and os.path.exists(os.path.join(DIR, "READY")):     # READY = copy finished and verified
            try:
                con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, check_same_thread=False, timeout=5)
                con.execute("select 1 from meta limit 1").fetchall()
                _c[key] = con
            except sqlite3.Error:
                _c[key] = None
    return _c[key]

def available():
    return _open(INDEX, "i") is not None

def snapshot():
    """Date of the CourtListener bulk snapshot behind the index, e.g. '2026-09-30' ('' if unknown)."""
    con = _open(INDEX, "i")
    if not con: return ""
    try:
        r = con.execute("select v from meta where k='index_date'").fetchone()
        return r[0] if r else ""
    except sqlite3.Error:
        return ""

def lookup(vol, forms, page):
    """Clusters filed under `vol <reporter> page`. `forms` = the ways the reporter is written ('F.3d', 'F3d', ...);
    CourtListener stores one of them, spaces vary, so every form is tried with spaces removed.
    -> [{'id', 'case_name', 'case_name_full', 'date', 'url'}]"""
    con = _open(INDEX, "i")
    if not con: return []
    reps = sorted({re.sub(r"\s+", "", f) for f in forms})
    q = ("select distinct c.id, c.case_name, c.case_name_full, c.date_filed, c.slug from citations x "
         "join clusters c on c.id = x.cluster_id where x.volume = ? and x.page = ? "
         "and replace(x.reporter, ' ', '') in (%s) limit 12" % ",".join("?" * len(reps)))
    try:
        rows = con.execute(q, [str(vol), str(page)] + reps).fetchall()
    except sqlite3.Error:
        return []
    return [{"id": r[0], "case_name": r[1] or "", "case_name_full": r[2] or "", "date": r[3] or "",
             "url": URL % (r[0], r[4] or "x")} for r in rows]

def text(cluster_id):
    """The opinion text of a cluster (lead/combined first, then the rest), or None when the store has none."""
    con = _open(TEXT, "t")
    if not con: return None
    try:
        rows = con.execute("select text, codec from opinions where cluster_id = ? order by "
                           "case type when '010combined' then 0 when '020lead' then 1 else 2 end", (cluster_id,)).fetchall()
    except sqlite3.Error:
        return None
    parts = []
    for blob, codec in rows:
        try:
            if codec == "zstd":
                if _unz is None: return None
                parts.append(_unz(blob).decode("utf-8", "replace"))
            else:
                parts.append(blob.decode("utf-8", "replace") if isinstance(blob, (bytes, bytearray)) else str(blob))
        except Exception:
            continue
    return "\n\n".join(parts) if parts else None

def stats():
    out = {"available": available(), "snapshot": snapshot(), "text": False}
    con = _open(TEXT, "t")
    if con:
        try:
            m = dict(con.execute("select k, v from meta").fetchall())
            out.update(text=bool(m.get("text_date")), text_rows=int(m.get("text_rows") or 0))
        except sqlite3.Error:
            pass
    return out
