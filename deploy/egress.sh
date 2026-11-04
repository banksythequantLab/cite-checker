#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Host-kernel egress allow-list for the cite container.
#
# The app container may talk to exactly two hosts, on 443 only:
#   courtlistener.com         (opinions, citation lookup)
#   api.vultrinference.com    (Vultr Serverless Inference)
# Everything else leaving the cite bridge is LOGGED and REJECTED by iptables in
# the DOCKER-USER chain -- the kernel refuses it, not our code. Caddy lives on a
# second bridge so Let's Encrypt still works.
#
# Idempotent; re-run from a systemd timer so the ipset tracks DNS changes.
# ---------------------------------------------------------------------------
set -euo pipefail
BR="${CITE_BRIDGE:-br-cite}"
SET="cite-allow"
HOSTS=(courtlistener.com www.courtlistener.com api.vultrinference.com)

ipset create "$SET" hash:ip -exist
ipset create "${SET}-new" hash:ip -exist
ipset flush "${SET}-new"
for h in "${HOSTS[@]}"; do
  for ip in $(getent ahostsv4 "$h" | awk '{print $1}' | sort -u); do
    ipset add "${SET}-new" "$ip" -exist
  done
done
ipset swap "${SET}-new" "$SET"
ipset destroy "${SET}-new"

# Rebuild our rules in DOCKER-USER (Docker consults it before its own rules).
iptables -N DOCKER-USER 2>/dev/null || true
iptables -F DOCKER-USER
iptables -A DOCKER-USER -i "$BR" -o "$BR" -j RETURN          # caddy <-> cite on the same bridge
iptables -A DOCKER-USER -i "$BR" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A DOCKER-USER -i "$BR" -p tcp --dport 443 -m set --match-set "$SET" dst -j RETURN
iptables -A DOCKER-USER -i "$BR" -m limit --limit 10/min -j LOG --log-prefix "CITE-EGRESS-BLOCKED " --log-level 4
iptables -A DOCKER-USER -i "$BR" -j REJECT --reject-with icmp-port-unreachable
iptables -A DOCKER-USER -j RETURN

echo "egress allow-list on $BR: $(ipset list "$SET" | grep -c '^[0-9]') address(es) for ${HOSTS[*]}"
