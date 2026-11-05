#!/usr/bin/env bash
# Vultr user_data for a fresh Ubuntu 24.04 Cloud Compute instance.
# Rendered by deploy/vultr_create.py, which fills in the secrets from the
# operator's local .env (never committed). Logs to /var/log/cite-init.log.
set -euxo pipefail
exec >>/var/log/cite-init.log 2>&1

REPO="${REPO:-https://github.com/banksythequantLab/cite-checker.git}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git
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

chmod +x deploy/*.sh
docker compose up -d --build
echo "CITE-INIT-DONE"
