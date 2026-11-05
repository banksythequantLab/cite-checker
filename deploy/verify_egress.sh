#!/usr/bin/env bash
# The sealing proof for the deployed app. Run on the VM after `docker compose up`.
# Every probe runs INSIDE the cite container, so what it reports is what the
# app itself can and cannot reach.
#
#   app network = Docker INTERNAL bridge  -> no route off the host (kernel)
#   egress-proxy = the only door          -> allow-list by HOSTNAME, 443 only,
#                                            every refusal logged by name
set -uo pipefail
cd "$(dirname "$0")/.."
pass=0; fail=0
ok(){ echo "  PASS  $1"; pass=$((pass+1)); }
no(){ echo "  FAIL  $1"; fail=$((fail+1)); }
inpy(){ docker compose exec -T -e HTTPS_PROXY= -e HTTP_PROXY= cite python3 - 2>&1 | tail -1; }
direct(){ printf 'import socket\ntry:\n    socket.create_connection(("%s",%s),timeout=5).close(); print("open")\nexcept Exception as e:\n    print("refused:",type(e).__name__)\n' "$1" "$2" | inpy; }
viaproxy(){ printf 'import httpx\ntry:\n    r=httpx.get("https://%s/",proxy="http://egress-proxy:3128",timeout=15,follow_redirects=False); print("http",r.status_code)\nexcept Exception as e:\n    print("refused:",type(e).__name__,str(e)[:60])\n' "$1" | inpy; }

echo "== container posture =="
docker compose exec -T cite id | grep -q 'uid=65534' && ok "runs as nobody (65534)" || no "not running as nobody"
docker compose exec -T cite sh -c 'touch /app/x 2>/dev/null' && no "root filesystem is writable" || ok "root filesystem is read-only"
docker compose exec -T cite python3 -c "import os;os.setuid(0)" 2>/dev/null && no "could become root" || ok "cannot escalate (caps dropped, no-new-privileges)"
docker network inspect app_cite-net -f '{{.Internal}}' 2>/dev/null | grep -q true && ok "app network is INTERNAL (no route off the host)" || no "app network is not internal"

echo "== direct egress (bypassing the proxy) =="
r=$(direct 1.1.1.1 443);           [ "$r" != open ] && ok "1.1.1.1:443 direct: REFUSED by the kernel ($r)" || no "1.1.1.1:443 reachable directly -- not sealed"
r=$(direct courtlistener.com 443); [ "$r" != open ] && ok "courtlistener.com:443 direct: REFUSED (must go through the door)" || no "courtlistener.com reachable directly"

echo "== through the door =="
r=$(viaproxy www.courtlistener.com);   case "$r" in http*) ok "www.courtlistener.com via proxy: $r";; *) no "www.courtlistener.com via proxy: $r";; esac
r=$(viaproxy api.vultrinference.com);  case "$r" in http*) ok "api.vultrinference.com via proxy: $r";; *) no "api.vultrinference.com via proxy: $r";; esac
r=$(viaproxy example.com);             case "$r" in http*) no "example.com via proxy: $r -- not sealed";; *) ok "example.com via proxy: REFUSED ($r)";; esac
r=$(viaproxy intake.exfil-example.invalid); case "$r" in http*) no "exfil host via proxy: $r";; *) ok "intake.exfil-example.invalid via proxy: REFUSED";; esac

echo "== refusals were recorded, by hostname =="
n=$(docker compose logs --no-log-prefix egress-proxy 2>/dev/null | grep -c '"refused"')
[ "${n:-0}" -gt 0 ] && ok "$n refusal(s) in the egress log" || no "no refusals logged"
docker compose logs --no-log-prefix egress-proxy 2>/dev/null | grep '"refused"' | tail -3 | sed 's/^/       /'

echo; echo "================  $pass passed, $fail failed  ================"
[ "$fail" -eq 0 ]
