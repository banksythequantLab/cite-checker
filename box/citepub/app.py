# -*- coding: utf-8 -*-
"""citepub - the public face of the box's citation checker (cite.nota.lawyer).

One engine: /opt/banksy/lex/cite_check.py, the same code behind LEX > CITES on the panel (Lex library first,
then the nationwide CourtListener index in lex/national). This file only adds what a public page needs:
the web page, file upload parsing, per-address rate limits, size caps, and a translation of the checker's
result into the page's cards. It holds no matter data and is started by systemd with the rest of
/opt/banksy hidden from it (see citepub.service)."""
import os, sys, threading

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

HERE = os.path.dirname(os.path.abspath(__file__))
LEX_DIR = os.environ.get("LEX_DIR", "/opt/banksy/lex")
sys.path.insert(0, HERE); sys.path.insert(0, LEX_DIR)
import extract_file, ratelimit          # noqa: E402
import cite_check as CC                 # noqa: E402

MAX_CHARS = int(os.environ.get("CITEPUB_MAX_CHARS", 300_000))
MAX_CITES = int(os.environ.get("CITEPUB_MAX_CITES", 250))
_slots = threading.BoundedSemaphore(int(os.environ.get("CITEPUB_CONCURRENCY", 2)))

app = FastAPI(title="Legal Cite Checker", docs_url=None, redoc_url=None, openapi_url=None)


def _db():
    """Lex connection for one check: read-only, with a ceiling on any single statement."""
    if CC.LX is None:
        return None
    cred = os.environ.get("CITEPUB_DB_ENV")          # systemd LoadCredential path; falls back to lex_ask's own
    if cred:
        CC.LX.SECRETS = cred
    conn = CC.LX.db()
    conn.execute("set default_transaction_read_only = on")
    return conn


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    if request.method == "POST":
        ip = ratelimit.client_ip(request.headers, request.client.host if request.client else "?")
        cf = request.headers.get("cf-connecting-ip")            # behind a Cloudflare tunnel this is the visitor
        ok, why = ratelimit.check(request.url.path, cf or ip)
        if not ok:
            return JSONResponse({"ok": False, "detail": why}, status_code=429, headers={"Retry-After": "60"})
    return await call_next(request)


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "ui", "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/og.png")
def og():
    return FileResponse(os.path.join(HERE, "ui", "og.png"), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/health")
def health():
    nat = CC.NAT.stats() if getattr(CC, "NAT", None) else {"available": False}
    lex = False
    try:
        conn = _db()
        if conn is not None:
            conn.execute("select 1").fetchone(); conn.close(); lex = True
    except Exception:
        lex = False
    return {"ok": bool(lex or nat.get("available")), "engine": "box", "lex": lex, "national": nat}


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read(extract_file.MAX_UPLOAD + 1)
    try:
        text = extract_file.extract(file.filename or "", data)
    except extract_file.ExtractError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "filename": file.filename, "chars": len(text), "text": text}


STATUS = {"mismatch": "WRONG_CASE", "not_found": "NOT_FOUND", "repealed": "REPEALED", "not_covered": "NOT_COVERED",
          "short": "SHORT_CITE", "error": "ERROR"}


def _card(c: dict) -> dict:
    quotes = [{"quote": q.get("quote", ""), "state": q.get("result"), "verified": q.get("result") == "exact",
               "detail": q.get("detail") or ""} for q in c.get("quotes") or []]
    s = c.get("status")
    if s == "verified":
        status = "VERIFIED" if (quotes or c.get("kind") != "case") else "UNQUOTED"
    elif s == "check":
        # MISQUOTE only when the case's own text was searched; a quote missing from citing opinions alone is a CHECK
        status = "MISQUOTE" if (c.get("has_text") and any(q["state"] == "missing" for q in quotes)) else "CHECK"
    else:
        status = STATUS.get(s, "CHECK")
    out = {"citation": c.get("cite", ""), "case_name_in_brief": c.get("name") or ("" if c.get("kind") == "case" else c.get("kind", "")),
           "status": status, "kind": c.get("kind"), "notes": list(c.get("notes") or []), "quotes": quotes}
    nat, found = c.get("national"), c.get("found")
    if nat:
        out.update(source="CourtListener", cl_case_name="%s (%s)" % (nat["case_name"], nat.get("date") or "no date"), cl_url=nat.get("url"))
    elif isinstance(found, dict) and found.get("case_name"):
        tail = ", ".join(str(x) for x in (found.get("court"), found.get("date")) if x)
        out.update(source="NY library", cl_case_name=found["case_name"] + (" — " + tail if tail else ""), cl_url=None)
    elif isinstance(found, dict) and found:                      # statutes / slip opinions: show what the library holds
        out.update(source="NY library", cl_case_name="; ".join(str(v) for v in found.values() if v and not isinstance(v, (dict, list)))[:200], cl_url=None)
    return out


@app.post("/api/check")
def check(text: str = Form(...)):
    if len(text) > MAX_CHARS:
        raise HTTPException(413, "that is %d characters; the limit here is %d" % (len(text), MAX_CHARS))
    if len(CC.scan(text)[1]) > MAX_CITES:
        raise HTTPException(413, "more than %d citations in one document; split it and check the parts" % MAX_CITES)
    if not _slots.acquire(timeout=45):
        return JSONResponse({"ok": False, "detail": "busy checking other briefs; try again in a minute"}, status_code=503,
                            headers={"Retry-After": "60"})
    conn = None
    try:
        conn = _db()
        res = CC.run(text, conn)
    except Exception as e:
        return JSONResponse({"ok": False, "detail": "the check failed: %s" % str(e)[:160]}, status_code=500)
    finally:
        _slots.release()
        try:
            if conn is not None: conn.close()
        except Exception:
            pass
    cards = [_card(c) for c in res["citations"]]
    counts = {}
    for c in cards:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {"ok": True, "citations": cards, "counts": counts, "limits": res.get("limits", ""),
            "note": "Two local libraries decide: the New York / Second Circuit library and CourtListener's nationwide index. "
                    "Quotes are string matches against the opinion text. A human reviews every flag."}
