#!/usr/bin/env python3
"""apply_abbrev_patch.py - case-name comparison treats standard abbreviations as the words they stand for.
'Heitner v Capital One, Natl. Assn.' and 'Heitner v. Capital One, N.A.' are the same case; before this the
checker called that a WRONG CASE. Usage: apply_abbrev_patch.py /opt/banksy/lex/cite_check.py  (keeps .bak-abbrev)"""
import sys, shutil
path = sys.argv[1]; s = open(path, encoding="utf-8").read()
if "_ABBREV" in s: print("already patched"); sys.exit(0)
old = '''def norm_name(s):
    s = s.lower().replace("’", "'"); s = re.sub(r"\\bv\\.?\\b|\\bvs\\.?\\b", " v ", s); s = re.sub(r"[^a-z0-9' ]", " ", s)'''
new = '''_ABBREV = [(re.compile(p), r) for p, r in (       # official-reporter and Bluebook abbreviations -> the full word, both sides
    (r"\\bn\\.\\s?a\\.(?!\\w)", " national association "), (r"\\bnatl\\b\\.?", "national"), (r"\\bnat'l\\b", "national"), (r"\\bassn\\b\\.?", "association"), (r"\\bass'n\\b", "association"),
    (r"\\bdept\\b\\.?", "department"), (r"\\bdep't\\b", "department"), (r"\\bbd\\b\\.?", "board"), (r"\\buniv\\b\\.?", "university"), (r"\\bintl\\b\\.?", "international"), (r"\\bint'l\\b", "international"),
    (r"\\bauth\\b\\.?", "authority"), (r"\\bhosp\\b\\.?", "hospital"), (r"\\bmgt\\b\\.?", "management"), (r"\\bmgmt\\b\\.?", "management"), (r"\\bctr\\b\\.?", "center"),
    (r"\\bcommn\\b\\.?", "commission"), (r"\\bcomm'n\\b", "commission"), (r"\\bcommr\\b\\.?", "commissioner"), (r"\\bcomm'r\\b", "commissioner"), (r"\\bins\\b\\.", "insurance"),
    (r"\\bedu?c\\b\\.", "education"), (r"\\bsch\\b\\.", "school"), (r"\\bdist\\b\\.", "district"), (r"\\bfedn\\b\\.?", "federation"), (r"\\bsoc\\b\\.", "society"), (r"\\bsocy\\b\\.?", "society"))]
def norm_name(s):
    s = s.lower().replace("’", "'")
    for rx, full in _ABBREV: s = rx.sub(full, s)
    s = re.sub(r"\\bv\\.?\\b|\\bvs\\.?\\b", " v ", s); s = re.sub(r"[^a-z0-9' ]", " ", s)'''
if s.count(old) != 1: print("ANCHOR matched %d times - nothing written" % s.count(old)); sys.exit(2)
shutil.copy2(path, path + ".bak-abbrev"); open(path, "w", encoding="utf-8").write(s.replace(old, new)); print("patched; backup at %s.bak-abbrev" % path)
