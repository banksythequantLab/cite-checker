#!/usr/bin/env bash
# Vultr user_data for a fresh Ubuntu 24.04 Cloud Compute instance.
# Rendered by deploy/vultr_create.py, which fills in the secrets from the
# operator's local .env (never committed). Logs to /var/log/cite-init.log.
set -euxo pipefail
exec >>/var/log/cite-init.log 2>&1

REPO="${REPO:-https://github.com/banksythequantLab/cite-checker.git}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ipset iptables
command -v docker >/dev/null || { curl -fsSL https://get.docker.com | sh; }
systemctl enable --now docker

install -d /opt/cite
git clone "$REPO" /opt/cite/app || (cd /opt/cite/app && git pull)
cd /opt/cite/app

umask 077
cat > .env <<EOF
COURTLISTENER_TOKEN=__COURTLISTENER_TOKEN__
VULTR_INFERENCE_API_KEY=__VULTR_INFERENCE_API_KEY__
DOCKET_MODEL=glm-5.3-flash
SITE_ADDRESS=__SITE_ADDRESS__
EOF
umask 022

# the allow-list, refreshed every 10 minutes so DNS changes don't break it
cat >/etc/systemd/system/cite-egress.service <<UNIT
[Unit]
Description=cite egress allow-list
After=docker.service
[Service]
Type=oneshot
ExecStart=/opt/cite/app/deploy/egress.sh
UNIT
cat >/etc/systemd/system/cite-egress.timer <<UNIT
[Unit]
Description=refresh cite egress allow-list
[Timer]
OnBootSec=1min
OnUnitActiveSec=10min
[Install]
WantedBy=timers.target
UNIT
chmod +x deploy/*.sh
systemctl daemon-reload
systemctl enable --now cite-egress.timer

docker compose up -d --build
sleep 5
bash deploy/egress.sh
echo "CITE-INIT-DONE"
