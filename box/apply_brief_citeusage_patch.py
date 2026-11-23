#!/usr/bin/env python3
"""Adds a Monday-only 'Public cite checker' line to the morning brief (visits and checks for the last 7 days).
Only a box that serves the public page has anything to report; everywhere else the section is silently absent."""
import shutil
p = "/opt/banksy/mailguard/morning_brief.py"; s = open(p, encoding="utf-8").read()
if "_cite_usage" in s: print("already patched"); raise SystemExit
fn = '''def _cite_usage(days=7):
    """One line on the public citation checker's last week (counts only), or [] when this box does not serve it."""
    import subprocess
    sh = "/opt/banksy/lex/citepub/usage.sh"
    if not (os.path.exists(sh) and os.path.exists("/etc/systemd/system/citepub.service")): return []
    try: out = subprocess.run(["sudo", "-n", sh, str(days)], capture_output=True, text=True, timeout=20).stdout
    except Exception: return []
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 6 and f[0] == "total":
            try: v, c, ci, up = int(f[1]), int(f[2]), int(f[3]), int(f[4])
            except ValueError: return []
            return ["Last %d days: %d visit%s, %d brief%s checked (%d citation%s), %d file upload%s. Counts only; no text or addresses are kept."
                    % (days, v, "" if v == 1 else "s", c, "" if c == 1 else "s", ci, "" if ci == 1 else "s", up, "" if up == 1 else "s")]
    return []

'''
a = "def _on(sec):\n"; assert s.count(a) == 1; s = s.replace(a, fn + a)
a = '''    if nl:
        ride.append(("New decisions worth a look", nl))
'''
b = a + '''    try:                           # Nov 20: public cite checker usage - Mondays only, rides along, never makes the brief send by itself
        cu = _cite_usage() if (_weekday() == 0 and _on("citeusage")) else []
    except Exception:
        cu = []
    if cu:
        ride.append(("Public cite checker (cite.nota.lawyer)", cu))
'''
assert s.count(a) == 1; s = s.replace(a, b)
shutil.copy2(p, p + ".bak-citeusage"); open(p, "w", encoding="utf-8").write(s); print("patched")
