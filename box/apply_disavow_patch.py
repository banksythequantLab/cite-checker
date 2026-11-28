#!/usr/bin/env python3
"""cite_check.py + cite_index.py: a citation that a court lists as nonexistent must count against it, not for it.

Found Nov 28, 2026: the library learns that a citation exists from every opinion that prints it next to a case name.
Phoenix Fashion v. Saadia (2d Cir. Nov 17, 2026) prints three fabricated citations in order to call them nonexistent,
so after it was ingested the checker reported those three as printed in 1 opinion, i.e. verified.
Now: a printed citation whose surrounding words say it does not exist (nonexistent/fictitious/fabricated case, could not
locate, hallucinated, phantom citation ...) is stored under name_key '=disavowed' and never counts as support. A
citation with no other support that a court disavowed is reported NOT FOUND, naming the decision that disavowed it.
Requires a full index rebuild afterwards:  cite_index.py build
Usage: apply_disavow_patch.py [lex_dir]"""
import sys, shutil, os
D = sys.argv[1] if len(sys.argv) > 1 else "/opt/banksy/lex"
def edit(path, pairs, tag):
    s = open(path, encoding="utf-8").read()
    if "disavow" in s: print(path, "already patched"); return
    for a, b in pairs:
        assert s.count(a) == 1, (path, a[:70]); s = s.replace(a, b)
    shutil.copy2(path, path + ".bak-" + tag); open(path, "w", encoding="utf-8").write(s); print(path, "patched")

CC = os.path.join(D, "cite_check.py")
edit(CC, [
 ("def clean(t):\n", r'''_FAKE = r"(?:non-?existent|fictitious|fabricated|fake|bogus|made-up|phantom|hallucinated)"
_KIND = r"(?:cases?|citations?|authorit\w+|decisions?|opinions?)"
DISAVOW_LIST = re.compile(_FAKE + r"\s+" + _KIND + r"[^.;]{0,60}?(?::|\bsuch as\b|\bincluding\b|\bnamely\b|\be\.g\.)", re.I)   # "relied on the following nonexistent cases: A; B; C"
DISAVOW_AFTER = re.compile(r"^[^;]{0,45}?(?:,|—|–|\()\s*(?:a|an|which (?:is|are|was|were)|both|each|all)?\s*" + _FAKE + r"\b"
                           r"|^[^;]{0,60}?\b(?:that|which)\s+(?:does|do|did)\s+not\s+exist", re.I)                            # "X, 123 F.3d 4 (2020), a nonexistent case"
_SENT_END = re.compile(r"\)\.\s|\.\s+(?:The|This|That|We|Here|In|Plaintiffs?|Defendants?|Counsel|Accordingly|Moreover|However|Finally|Further)\b")
def disavowed(t, start, end):
    """True when a court prints this citation in order to say the case does not exist: inside a list introduced as
    nonexistent/fictitious/fabricated cases, or labelled that way right after it. A court listing fabricated citations is
    not evidence that they exist. Deliberately narrow: a real case cited near the word 'fake' is not disavowed."""
    for m in DISAVOW_LIST.finditer(t, max(0, start - 300), start):
        if not _SENT_END.search(t, m.end(), start): return True
    return bool(DISAVOW_AFTER.search(t[end:end + 150]))

'''.lstrip() + "def clean(t):\n"),
 ('''        cols = "name, n, samples" + (", yr" if _IDX.get("yr") else ", null")''',
  '''        cols = "name, n, samples" + (", yr" if _IDX.get("yr") else ", null") + ", name_key"'''),
 ('''        support, other, ids, yrs = 0, {}, [], []
        for nm, n, samples, yr in rows:
''', '''        support, other, ids, yrs, dis, dis_ids = 0, {}, [], [], 0, []
        for nm, n, samples, yr, key in rows:
            if key == "=disavowed": dis += n; dis_ids += list(samples or []); continue       # a court said it does not exist
'''),
 ('''        return {"support": support, "other": other, "texts": [clean(t or "") for t in texts], "printed": sum(r[1] for r in rows), "year": _mode_year(yrs)}''',
  '''        return {"support": support, "other": other, "texts": [clean(t or "") for t in texts], "printed": sum(r[1] for r in rows), "year": _mode_year(yrs),
                "disavowed": dis, "dis_ids": dis_ids[:3]}'''),
 ('''        conn.rollback(); return {"support": 0, "other": {}, "texts": [], "printed": -1, "year": None}''',
  '''        conn.rollback(); return {"support": 0, "other": {}, "texts": [], "printed": -1, "year": None, "disavowed": 0, "dis_ids": []}'''),
 ('''    support, other, texts = set(), {}, []
    for oid, cname, court, date, text in rows:
        t = clean(text or ""); hit = False
        for m in rx.finditer(t):
''', '''    support, other, texts, dis = set(), {}, [], set()
    for oid, cname, court, date, text in rows:
        t = clean(text or ""); hit = False
        for m in rx.finditer(t):
            if disavowed(t, m.start(), m.end()): dis.add(oid); hit = True; continue
'''),
 ('''    return {"support": len(support), "other": other, "texts": texts, "printed": len(rows), "year": None}''',
  '''    return {"support": len(support), "other": other, "texts": texts, "printed": len(rows), "year": None, "disavowed": len(dis - support), "dis_ids": list(dis - support)[:3]}'''),
 ('''    status, own_text, natok = national(c, forms, status, notes, own_text, support, order)
''', '''    status, own_text, natok = national(c, forms, status, notes, own_text, support, order)
    if co.get("disavowed") and not support:                 # a court in the library lists this citation as nonexistent
        who = conn.execute("select case_name, court_id, decision_date from opinions where id = any(%s) order by decision_date desc limit 1",
                           (co.get("dis_ids") or [],)).fetchone() if co.get("dis_ids") else None
        where = " (%s, %s, %s)" % (who[0], (LX.COURT.get(who[1], who[1]) if LX else who[1]), who[2]) if who else ""
        if natok:
            notes.append("a decision in the library lists this citation among nonexistent authorities%s - confirm it by hand" % where)
            if status == "verified": status = "check"
        else:
            status = "not_found"; notes.append("a court decision in the library lists this citation as a nonexistent case%s" % where)
'''),
], "disavow")

CI = os.path.join(D, "cite_index.py")
edit(CI, [
 ('''        key = " ".join(C.norm_name(nm))[:80]
        if not key: continue
''', '''        key = "=disavowed" if C.disavowed(t, m.start(), m.end()) else " ".join(C.norm_name(nm))[:80]   # a court calling it nonexistent is not support
        if not key: continue
'''),
], "disavow")
