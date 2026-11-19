#!/usr/bin/env python3
"""apply_national_patch.py - merge the Legal Cite Checker's nationwide lookup into the box's cite_check.py.

Usage: apply_national_patch.py /opt/banksy/lex/cite_check.py
Keeps cite_check.py.bak-national beside it. Every edit is an exact-text replacement that must match once;
if any anchor is missing nothing is written. Re-running on a patched file is a no-op."""
import sys, shutil

path = sys.argv[1]
src = open(path, encoding="utf-8").read()
if "cl_national" in src:
    print("already patched"); sys.exit(0)
out = src
def sub(old, new, label):
    global out
    n = out.count(old)
    if n != 1:
        print("ANCHOR %s matched %d times - nothing written" % (label, n)); sys.exit(2)
    out = out.replace(old, new)

# 1 -- reporters the box never extracted (other states, F. App'x): no Lex courts, no volume ceiling ---------------
sub('''    ("F Supp", ["F Supp", "F. Supp.", "F.Supp."], FEDDIST, 999), ("BR", ["BR", "B.R."], {"nysb", "nyeb", "nywb", "nynb"}, 700), ("F", ["F", "F."], {"ca2"}, 300),
]''', '''    ("F Supp", ["F Supp", "F. Supp.", "F.Supp."], FEDDIST, 999), ("BR", ["BR", "B.R."], {"nysb", "nyeb", "nywb", "nynb"}, 700), ("F", ["F", "F."], {"ca2"}, 300),
    # nationwide reporters - not held in Lex; settled by the CourtListener index (cl_national.py). First form = CourtListener's spelling.
    ("F Appx", ["F. App'x", "F. App’x", "F. Appx", "Fed. Appx.", "Fed. App'x"], set(), 0),
    ("P3d", ["P.3d", "P. 3d"], set(), 0), ("P2d", ["P.2d", "P. 2d"], set(), 0), ("P", ["P."], set(), 0),
    ("A3d", ["A.3d", "A. 3d"], set(), 0), ("A2d", ["A.2d", "A. 2d"], set(), 0), ("A", ["A."], set(), 0),
    ("NW3d", ["N.W.3d", "N.W. 3d"], set(), 0), ("NW2d", ["N.W.2d", "N.W. 2d"], set(), 0), ("NW", ["N.W."], set(), 0),
    ("SE2d", ["S.E.2d", "S.E. 2d"], set(), 0), ("SE", ["S.E."], set(), 0),
    ("SW3d", ["S.W.3d", "S.W. 3d"], set(), 0), ("SW2d", ["S.W.2d", "S.W. 2d"], set(), 0), ("SW", ["S.W."], set(), 0),
    ("So3d", ["So. 3d", "So.3d"], set(), 0), ("So2d", ["So. 2d", "So.2d"], set(), 0), ("So", ["So."], set(), 0),
    ("Cal5th", ["Cal. 5th", "Cal.5th"], set(), 0), ("Cal4th", ["Cal. 4th", "Cal.4th"], set(), 0), ("Cal3d", ["Cal. 3d", "Cal.3d"], set(), 0),
    ("Cal2d", ["Cal. 2d", "Cal.2d"], set(), 0), ("Cal", ["Cal."], set(), 0),
    ("CalApp5th", ["Cal. App. 5th", "Cal.App.5th"], set(), 0), ("CalApp4th", ["Cal. App. 4th", "Cal.App.4th"], set(), 0),
    ("CalApp3d", ["Cal. App. 3d", "Cal.App.3d"], set(), 0), ("CalApp2d", ["Cal. App. 2d", "Cal.App.2d"], set(), 0),
    ("CalRptr3d", ["Cal. Rptr. 3d", "Cal.Rptr.3d"], set(), 0), ("CalRptr2d", ["Cal. Rptr. 2d", "Cal.Rptr.2d"], set(), 0), ("CalRptr", ["Cal. Rptr.", "Cal.Rptr."], set(), 0),
    ("Ill2d", ["Ill. 2d", "Ill.2d"], set(), 0), ("IllApp3d", ["Ill. App. 3d", "Ill.App.3d"], set(), 0),
    ("NJSuper", ["N.J. Super.", "N.J.Super."], set(), 0), ("NJ", ["N.J."], set(), 0),
    ("Mass", ["Mass."], set(), 0), ("MassAppCt", ["Mass. App. Ct.", "Mass.App.Ct."], set(), 0),
    ("Pa", ["Pa."], set(), 0), ("PaSuper", ["Pa. Super.", "Pa.Super."], set(), 0),
    ("OhioSt3d", ["Ohio St. 3d", "Ohio St.3d"], set(), 0), ("OhioSt2d", ["Ohio St. 2d", "Ohio St.2d"], set(), 0),
]''', "REPS")

# 2 -- import the nationwide module (optional: without the data files the checker behaves as before) --------------
sub('''ABBR = sorted([k for k in LAW if k.isupper() and " " not in k and len(k) <= 6], key=len, reverse=True)''',
    '''try:
    import cl_national as NAT
except Exception:
    NAT = None
ABBR = sorted([k for k in LAW if k.isupper() and " " not in k and len(k) <= 6], key=len, reverse=True)''', "import")

# 3 -- helpers: explanatory parentheticals, and the nationwide second opinion -----------------------------------
sub('''def check_quote(q, texts):''', '''def quotes_after(text, end):
    """Bluebook explanatory parentheticals right after a citation - 550 U.S. 544 (2007) ("plausible on its face") -
    belong to THAT citation, not the next one. Consecutive parentheticals are all read; nesting is balanced.
    -> (quotes, where the parentheticals end)."""
    quotes = []
    while True:
        m = re.match(r"\\s*\\(", text[end:end + 8])
        if not m: return quotes, end
        i = end + m.end(); depth = 1; limit = min(len(text), i + 900)
        while i < limit and depth:
            ch = text[i]
            if ch == "(": depth += 1
            elif ch == ")": depth -= 1
            i += 1
        if depth: return quotes, end
        quotes += [q.strip() for q in re.findall(r"[\\"“]([^\\"”]{20,700})[\\"”]", text[end + m.end():i - 1])]
        end = i

def _nat_sim(name, hit):
    """Does the draft's case name match a CourtListener cluster? Full names go through name_sim; a short form
    ('Twombly' for 'Bell Atlantic Corp. v. Twombly') matches when every distinctive word of it is in the full name."""
    best = 0.0
    for full in (hit.get("case_name") or "", hit.get("case_name_full") or ""):
        if not full: continue
        best = max(best, name_sim(name, full))
        a = [t for t in norm_name(name) if len(t) >= 4]; b = set(norm_name(full))
        if a and len(_sides(name)) == 1 and all(t in b for t in a): best = max(best, 0.75)
    return best

def _nat_clean(t):
    return re.sub(r"\\s?\\*+\\d+(?=\\W)", " ", clean(t or ""))          # CourtListener star pages: "*46"

def national(c, forms, status, notes, own_text, support, order):
    """Second opinion from the nationwide CourtListener index, used only where Lex could not settle the citation or
    holds no text of the case. It never downgrades a citation Lex verified. -> (status, own_text, confirmed)"""
    if not (NAT and NAT.available()) or order: return status, own_text, False
    if own_text and status == "verified": return status, own_text, False
    hits = NAT.lookup(c["vol"], forms, c["page"]); snap = NAT.snapshot()
    src = "the nationwide CourtListener index" + (" (%s snapshot)" % snap if snap else "")
    if not hits:
        if status in ("not_found", "check", "mismatch"):
            notes.append("%s has no case at this citation either. That index has gaps (unpublished and some state decisions) - confirm in Westlaw or Lexis before relying on it or striking it" % src)
        return status, own_text, False
    if not c["name"]:
        h = hits[0]; c["national"] = {"case_name": h["case_name"], "date": h["date"], "url": h["url"], "match": None}
        notes.append("%s files this citation under “%s” (%s)" % (src, h["case_name"], h["date"] or "no date"))
        if not own_text and len(hits) == 1:
            t = NAT.text(h["id"])
            if t: own_text = _nat_clean(t); c["text_source"] = "courtlistener"
        return status, own_text, False
    s, h = sorted(((_nat_sim(c["name"], x), x) for x in hits), key=lambda x: -x[0])[0]
    if s < 0.7:
        if status != "verified":
            status = "mismatch"; c["national"] = {"case_name": h["case_name"], "date": h["date"], "url": h["url"], "match": round(s, 2)}
            notes.append("%s files this citation under a different case: “%s” (%s)" % (src, h["case_name"], h["date"] or "no date"))
        return status, own_text, False
    c["national"] = {"case_name": h["case_name"], "date": h["date"], "url": h["url"], "match": round(s, 2)}
    if status == "mismatch":
        status = "check"; notes.append("but %s files it under this case: “%s” (%s) - the two sources disagree, read the opinion" % (src, h["case_name"], h["date"] or "no date"))
    elif status in ("not_found", "check") and not support:
        status = "verified"; notes[:] = [n for n in notes if n.startswith("subsequent history")]; notes.append("confirmed in %s: “%s” (%s)" % (src, h["case_name"], h["date"] or "no date"))
    y = c.get("year")
    if y and h["date"][:4].isdigit() and abs(int(h["date"][:4]) - int(y)) > 1 and status == "verified" and not support:
        status = "check"; notes.append("year: the draft says %s; CourtListener has it decided %s" % (y, h["date"]))
    if not own_text:
        t = NAT.text(h["id"])
        if t: own_text = _nat_clean(t); c["text_source"] = "courtlistener"
        else: notes.append("the nationwide index has the case but not its text, so quotations are checked only against opinions that cite it")
    return status, own_text, status == "verified"

def check_quote(q, texts):''', "helpers")

# 4 -- call it inside check_case, before the volume / year / quotation checks -----------------------------------
sub('''    if beyond and not support:
        status = "not_found"; notes.append("volume %s of %s is beyond the latest published (about %d)" % (c["vol"], canon, vmax))''',
    '''    status, own_text, natok = national(c, forms, status, notes, own_text, support, order)
    if beyond and not support and not natok:
        status = "not_found"; notes.append("volume %s of %s is beyond the latest published (about %d)" % (c["vol"], canon, vmax))''', "call")
sub('''    if not courts and status in ("check", "not_found") and not other:
        notes.append("%s cases are not held in the library; only other opinions citing them can confirm" % canon)''',
    '''    if not courts and status in ("check", "not_found") and not other and not c.get("national"):
        notes.append("%s cases are not held in the library; only other opinions citing them can confirm" % canon)''', "courts-note")
sub('''    qs = quotes_before(text, c["start"], prev_end); qres = []''',
    '''    pq, c["_qend"] = quotes_after(text, c["end"])
    qs = quotes_before(text, c["start"], prev_end) + pq; qres = []''', "quotes")

# 5 -- run(): a parenthetical's quotation must not be read again as the next citation's ---------------------------
sub('''        prev_end = c["end"]
''', '''        prev_end = max(prev_end, c.get("_qend") or c["end"])
''', "prev_end")
sub('''        for k in ("start", "end", "rep_raw", "_texts"): c.pop(k, None)''',
    '''        for k in ("start", "end", "rep_raw", "_texts", "_qend"): c.pop(k, None)''', "cleanup")

# 6 -- Westlaw cites: say plainly that nothing on the box can check them -----------------------------------------
sub('''SLIP_RE = re.compile(''', '''WL_RE = re.compile(r"(?<![\\w.])(?P<year>(?:19|20)\\d\\d)\\s+(?P<db>WL|U\\.S\\. Dist\\. LEXIS|U\\.S\\. App\\. LEXIS|LEXIS)\\s+(?P<num>\\d{3,8})(?![\\w])")
SLIP_RE = re.compile(''', "wl-re")
sub('''    for m in CITE_RE.finditer(text):
        if not free(*m.span()): continue
        taken.append(m.span())''', '''    for m in WL_RE.finditer(text):
        if free(*m.span()): taken.append(m.span()); out.append({"kind": "wl", "start": m.start(), "end": m.end(), "cite": m.group(0), "name": extract_name(text[:m.start()])})
    for m in CITE_RE.finditer(text):
        if not free(*m.span()): continue
        taken.append(m.span())''', "wl-scan")
sub('''            elif c["kind"] == "usc":''', '''            elif c["kind"] == "wl":
                c.update(status="not_covered", notes=["Westlaw / Lexis database citation: neither the library nor the nationwide index is keyed by these numbers - pull it in Westlaw or Lexis and confirm the case exists"])
            elif c["kind"] == "usc":''', "wl-run")

# 6b -- Bluebook briefs: a name must not swallow the tail of the previous citation ("... (1957). People v Anderson, ...")
sub('''            t = tok.strip(",")
            if t[:1].isupper() or t.lower() in CONNECT or t[:1].isdigit() or "&" in t: keep.insert(0, tok)''',
    '''            t = tok.strip(",")
            if ")" in t or "]" in t: break
            if t[:1].isupper() or t.lower() in CONNECT or t[:1].isdigit() or "&" in t: keep.insert(0, tok)''', "name-tail")

# 6c -- tell callers whether the case's OWN text was available (a quote missing from citing opinions only is weaker)
sub('''    c.update(status=status, notes=notes, quotes=qres); c["_texts"] = ([own_text] if own_text else []) + ctexts''',
    '''    c.update(status=status, notes=notes, quotes=qres); c["has_text"] = bool(own_text); c["_texts"] = ([own_text] if own_text else []) + ctexts''', "has-text")

# 7 -- say what the check now covers -----------------------------------------------------------------------------
sub('''    return {"citations": cites, "counts": counts, "total": len(cites),
            "limits": "Checks that each citation exists in the box's library and is paired with the right case, the year, quotations and NY statute sections. "
                      "It does not tell you whether a case is still good law, and it cannot see cases the library doesn't hold (e.g. U.S. Supreme Court opinions, other circuits) except through opinions that cite them."}''',
    '''    nat = NAT.stats() if NAT else {"available": False}
    if nat.get("available"):
        limits = ("Checks that each citation exists and is paired with the right case, the year, quotations and NY statute sections - first against the box's own library "
                  "(New York and Second Circuit), then against a local copy of CourtListener's nationwide index%s for every other U.S. court. "
                  "It does not tell you whether a case is still good law. CourtListener is missing many unpublished and some state decisions, so a citation it does not have is a reason to look, not proof of a fake."
                  % (" (%s snapshot)" % nat["snapshot"] if nat.get("snapshot") else ""))
    else:
        limits = ("Checks that each citation exists in the box's library and is paired with the right case, the year, quotations and NY statute sections. "
                  "It does not tell you whether a case is still good law, and it cannot see cases the library doesn't hold (e.g. U.S. Supreme Court opinions, other circuits) except through opinions that cite them.")
    return {"citations": cites, "counts": counts, "total": len(cites), "national": nat, "limits": limits}''', "limits")

shutil.copy2(path, path + ".bak-national")
open(path, "w", encoding="utf-8").write(out)
print("patched; backup at %s.bak-national" % path)
