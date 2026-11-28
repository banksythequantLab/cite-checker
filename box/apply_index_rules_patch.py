#!/usr/bin/env python3
"""cite_index.py: rebuild the index once, by itself, when the rules that fill it change.
The nightly 'update' only indexes new opinions. When a release changes how citations are indexed (Nov 28 2026: citations a
court disavows go in as '=disavowed'), every existing row needs redoing. RULES names the current rules; 'update' compares it
with cite_index.rules and runs a full 'build' (about 5 minutes) when they differ, then records it. No one has to remember.
Usage: apply_index_rules_patch.py [path-to-cite_index.py]"""
import sys, shutil
p = sys.argv[1] if len(sys.argv) > 1 else "/opt/banksy/lex/cite_index.py"; s = open(p, encoding="utf-8").read()
if "RULES_FILE" in s: print("already patched"); raise SystemExit
def sub(a, b):
    global s; assert s.count(a) == 1, a[:60]; s = s.replace(a, b)
sub('STAMP = "/opt/banksy/lex/cite_index.stamp"\n',
    'STAMP = "/opt/banksy/lex/cite_index.stamp"\n'
    'RULES = "disavow-1"                      # bump when occurrences() changes; the next nightly update then rebuilds once\n'
    'RULES_FILE = "/opt/banksy/lex/cite_index.rules"\n')
sub('''def update():
    t0 = time.time(); stamp = dt.datetime.now().astimezone().isoformat()
''', '''def update():
    try: have = open(RULES_FILE).read().strip()
    except Exception: have = ""
    if have != RULES:
        print("index rules changed (%s -> %s): full rebuild" % (have or "none", RULES), flush=True)
        build(); open(RULES_FILE, "w").write(RULES); return
    t0 = time.time(); stamp = dt.datetime.now().astimezone().isoformat()
''')
sub('''    open(STAMP, "w").write(stamp)
    rows = w.execute''', '''    open(STAMP, "w").write(stamp); open(RULES_FILE, "w").write(RULES)
    rows = w.execute''')
shutil.copy2(p, p + ".bak-rules"); open(p, "w", encoding="utf-8").write(s); print("patched")
