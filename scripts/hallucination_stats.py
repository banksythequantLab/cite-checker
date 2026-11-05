#!/usr/bin/env python3
"""Reproduce the README table from Damien Charlotin's AI Hallucination Cases CSV.

    python3 scripts/hallucination_stats.py            # downloads the CSV
    python3 scripts/hallucination_stats.py path.csv   # or use a saved copy
"""
import collections, csv, re, sys, urllib.request

URL = "https://www.damiencharlotin.com/hallucinations/hallucinations/download.csv"
csv.field_size_limit(1 << 26)
src = sys.argv[1] if len(sys.argv) > 1 else urllib.request.urlretrieve(URL)[0]
rows = list(csv.DictReader(open(src, encoding="utf-8")))


def party(p):
    if "Judge" in p: return "judge"
    if re.search(r"Lawyer|Prosecutor|Defender|Paralegal", p): return "lawyer"
    if "Pro Se" in p: return "pro se"
    return "other"


by = collections.defaultdict(collections.Counter)
us = 0
for r in rows:
    m = re.search(r"(20\d\d)", r["Date"] or "")
    by[m.group(1) if m else "undated"][party(r["Party(ies)"])] += 1
    us += "USA" in (r["State(s)"] or "")
print(f"{len(rows)} decisions, {us} in U.S. courts")
print("year      lawyer  pro se  judge  other  total")
for y in sorted(by):
    c = by[y]
    print(f"{y:9} {c['lawyer']:6} {c['pro se']:7} {c['judge']:6} {c['other']:6} {sum(c.values()):6}")
