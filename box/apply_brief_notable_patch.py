#!/usr/bin/env python3
"""apply_brief_notable_patch.py - the morning brief gains a ride-along section, "New decisions worth a look", read from
/opt/banksy/lex/notable/latest.json (written by lex_notable.py). Like the other ride-alongs it never makes the brief
send by itself; a list older than 30 hours is not shown.   Usage: ... /opt/banksy/mailguard/morning_brief.py"""
import sys, shutil
path = sys.argv[1]; s = open(path, encoding="utf-8").read()
if "_notable()" in s: print("already patched"); sys.exit(0)
out = s
def sub(old, new, label):
    global out
    if out.count(old) != 1: print("ANCHOR %s matched %d times - nothing written" % (label, out.count(old))); sys.exit(2)
    out = out.replace(old, new)
sub('''def _on(sec):''', '''def _notable(max_age_h=30):
    """Lines for 'New decisions worth a look' from lex_notable.py's latest list; [] when there is none or it is stale."""
    import json as _j, datetime as _d
    try: d = _j.load(open("/opt/banksy/lex/notable/latest.json"))
    except Exception: return []
    try:
        if (_d.datetime.now(_d.timezone.utc) - _d.datetime.fromisoformat(d["generated"])).total_seconds() > max_age_h * 3600: return []
    except Exception: return []
    out = []
    for it in d.get("items", [])[:8]:
        line = "%s (%s, %s) [%s]" % (it.get("case_name", "")[:90], it.get("court", ""), it.get("date", ""), ", ".join(it.get("tags", [])))
        if it.get("summary"): line += ": " + it["summary"]
        elif it.get("quote"): line += ': "%s"' % it["quote"][:200]
        if it.get("why") and it.get("summary"): line += ' Flagged passage: "%s"' % it["why"][:200]
        if it.get("url"): line += "  " + it["url"]
        out.append(line)
    return out

def _on(sec):''', "def")
sub('''    has = bool(sections) or bool(ub_line) or (any(s[0] == "Unpaid invoices past due"''',
    '''    try:                           # Nov 19: notable new decisions ride along - never make the brief send by themselves
        nl = _notable() if _on("notable") else []
    except Exception:
        nl = []
    if nl:
        ride.append(("New decisions worth a look", nl))
    has = bool(sections) or bool(ub_line) or (any(s[0] == "Unpaid invoices past due"''', "ride")
shutil.copy2(path, path + ".bak-notable"); open(path, "w", encoding="utf-8").write(out); print("patched; backup at %s.bak-notable" % path)
