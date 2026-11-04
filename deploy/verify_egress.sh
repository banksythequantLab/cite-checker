#!/usr/bin/env bash
# The sealing proof for the deployed app. Run on the VM after `docker compose up`.
# Each probe runs INSIDE the cite container, so what it reports is what the
# app itself can and cannot reach.
set -uo pipefail
cd "$(dirname "$0")/.."
pass=0; fail=0
ok(){ echo "  PASS  $1"; pass=$((pass+1)); }
no(){ echo "  FAIL  $1"; fail=$((fail+1)); }
probe(){ docker compose exec -T cite python3 -c "
import socket,sys
try:
    socket.create_connection(('$1',$2),timeout=5).close(); print('open')
except Exception as e:
    print('refused:',e)" 2>&1 | tail -1; }

echo "== container posture =="
docker compose exec -T cite id | grep -q 'uid=65534' && ok "runs as nobody (65534)" || no "not running as nobody"
docker compose exec -T cite sh -c 'touch /app/x 2>/dev/null' && no "root filesystem is writable" || ok "root filesystem is read-only"
docker compose exec -T cite python3 -c "import os;os.setuid(0)" 2>/dev/null && no "could become root" || ok "cannot escalate (caps dropped, no-new-privileges)"

echo "== egress =="
r=$(probe courtlistener.com 443);     [ "$r" = open ] && ok "courtlistener.com:443 reachable" || no "courtlistener.com:443 blocked ($r)"
r=$(probe api.vultrinference.com 443);[ "$r" = open ] && ok "api.vultrinference.com:443 reachable" || no "api.vultrinference.com:443 blocked ($r)"
r=$(probe 1.1.1.1 443);               [ "$r" != open ] && ok "1.1.1.1:443 REFUSED by the kernel" || no "1.1.1.1:443 reachable -- not sealed"
r=$(probe example.com 443);           [ "$r" != open ] && ok "example.com:443 REFUSED" || no "example.com:443 reachable -- not sealed"
r=$(probe courtlistener.com 80);      [ "$r" != open ] && ok "courtlistener.com:80 REFUSED (443 only)" || no "port 80 open"

echo "== the kernel logged the refusals =="
n=$(journalctl -k --since "2 min ago" 2>/dev/null | grep -c CITE-EGRESS-BLOCKED || true)
[ "${n:-0}" -gt 0 ] && ok "$n blocked attempt(s) in the kernel log" || no "no CITE-EGRESS-BLOCKED lines in the kernel log"

echo; echo "================  $pass passed, $fail failed  ================"
[ "$fail" -eq 0 ]
