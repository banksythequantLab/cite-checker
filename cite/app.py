"""Cite-checker control plane: paste a brief, every citation is checked against
the real opinion. Nothing is auto-corrected; the human reviews each flag."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import courtlistener as CL      # noqa: E402
import extract as EX            # noqa: E402
import support                  # noqa: E402
import verify                   # noqa: E402
from inference import Vultr     # noqa: E402

UI = HERE.parent / "ui" / "index.html"
app = FastAPI(title="Cite Checker")
inf = Vultr()


@app.get("/", response_class=HTMLResponse)
def index():
    return UI.read_text() if UI.exists() else "<h1>Cite Checker</h1>"


@app.get("/og.png")
def og_image():
    return FileResponse(HERE.parent / "ui" / "og.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/health")
def health():
    import bulk
    idx = None
    if bulk.available():
        m = dict(bulk._q().execute("SELECT k, v FROM meta").fetchall())
        t = bulk._t()
        idx = {"index_date": m.get("index_date"),
               "text_date": t.execute("SELECT v FROM meta WHERE k='text_date'").fetchone()[0] if t else None}
    return {"ok": True, "courtlistener_token": bool(os.environ.get("COURTLISTENER_TOKEN")),
            "model": inf.model if inf.api_key else None, "bulk_index": idx}


def _context(text: str, raw_cite: str, width: int = 420) -> str:
    i = text.find(raw_cite)
    if i == -1:
        return ""
    lo = max(0, i - width)
    return text[lo:i + len(raw_cite)]


@app.post("/api/check")
def check(text: str = Form(...), find_support: int = Form(1)):
    try:
        findings = verify.check_brief(text)
    except CL.CLError as e:
        raise HTTPException(400, str(e))
    out = [f.to_dict() for f in findings]
    # model pass only for paraphrased, real, right-case citations -- run them
    # concurrently; each is an independent call to Vultr Inference
    jobs = []
    for d, f in zip(out, findings):
        if find_support and f.status == "UNQUOTED" and inf.api_key and f.cl_url:
            try:
                cid = int(f.cl_url.rstrip("/").split("/")[-2]) if "/opinion/" in f.cl_url else None
            except ValueError:
                cid = None
            if cid:
                jobs.append((d, cid, _context(text, f.citation)))

    def _one(job):
        d, cid, ctx = job
        try:
            opinion, _ = CL.opinion_text(cid)
            d["support"] = support.find_support(inf, ctx, opinion)
        except Exception as e:
            d["support"] = {"error": str(e)[:120]}

    if jobs:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_one, jobs))
    counts = {}
    for d in out:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    return {"ok": True, "citations": out, "counts": counts,
            "note": "Existence and case identity are CourtListener's data; quotes are "
                    "verbatim string matches; a model only proposes supporting passages "
                    "that are then verified verbatim. A human reviews every flag."}
