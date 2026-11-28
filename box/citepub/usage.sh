#!/usr/bin/env bash
# usage.sh - how much the public citation checker was used. Daily counts only; no brief text or addresses are kept.
#   sudo /opt/banksy/lex/citepub/usage.sh [days]      (default 14)
F=/var/lib/private/citepub/usage.json; [ -f "$F" ] || F=/var/lib/citepub/usage.json
[ -r "$F" ] || { echo "no usage recorded yet (or run with sudo)"; exit 0; }
python3 - "$F" "${1:-14}" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); days = sorted(d)[-int(sys.argv[2]):]
print("%-11s %7s %7s %9s %8s %9s   %s" % ("day", "visits", "checks", "citations", "uploads", "passages", "came from"))
tot = {}
for day in days:
    r = d[day]; frm = ", ".join("%s %d" % kv for kv in sorted(r.get("from", {}).items(), key=lambda x: -x[1])[:4])
    print("%-11s %7d %7d %9d %8d %9d   %s" % (day, r.get("visits", 0), r.get("checks", 0), r.get("citations", 0), r.get("uploads", 0), r.get("passage_requests", 0), frm))
    for k in ("visits", "checks", "citations", "uploads", "passage_requests", "robot_visits", "robot_checks", "demo_runs"): tot[k] = tot.get(k, 0) + r.get(k, 0)
print("%-11s %7d %7d %9d %8d %9d" % ("total", tot.get("visits", 0), tot.get("checks", 0), tot.get("citations", 0), tot.get("uploads", 0), tot.get("passage_requests", 0)))
print("demo runs (the one-click demo brief, not counted as checks): %d" % tot.get("demo_runs", 0))
print("not counted above - automated visits: %d, automated checks: %d (uptime monitor, scanners, scripts)" % (tot.get("robot_visits", 0), tot.get("robot_checks", 0)))
PY
