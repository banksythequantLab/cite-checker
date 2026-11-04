#!/usr/bin/env python3
"""Create the Vultr Cloud Compute instance that runs Cite Checker.

Reads VULTR_API_KEY plus the app secrets from the local .env (never committed),
renders deploy/cloud-init.sh into user_data, creates the instance, and waits
for a public IP. Usage:

    python3 deploy/vultr_create.py            # create
    python3 deploy/vultr_create.py --status   # list instances with the tag
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.vultr.com/v2"
TAG = "cite-checker"


def load_env() -> dict:
    env = dict(os.environ)
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def main() -> int:
    env = load_env()
    key = env.get("VULTR_API_KEY")
    if not key:
        print("VULTR_API_KEY missing (put it in .env)"); return 2
    h = {"Authorization": f"Bearer {key}"}
    c = httpx.Client(headers=h, timeout=60)

    if "--status" in sys.argv:
        r = c.get(f"{API}/instances", params={"tag": TAG}).json()
        for i in r.get("instances", []):
            print(i["id"], i["main_ip"], i["status"], i["server_status"], i["label"])
        return 0

    region = env.get("VULTR_REGION", "ewr")          # New Jersey
    plan = env.get("VULTR_PLAN", "vc2-1c-2gb")
    os_id = int(env.get("VULTR_OS_ID", "2284"))      # Ubuntu 24.04 LTS x64 (verified below)
    oses = c.get(f"{API}/os", params={"per_page": 500}).json()["os"]
    names = {o["id"]: o["name"] for o in oses}
    if "24.04" not in names.get(os_id, ""):
        cand = [o for o in oses if "Ubuntu 24.04" in o["name"] and "x64" in o["name"]]
        if not cand:
            print("could not find Ubuntu 24.04 in /v2/os"); return 2
        os_id = cand[0]["id"]
    print(f"os_id={os_id} ({names[os_id]}) region={region} plan={plan}")

    site = env.get("SITE_ADDRESS", ":80")
    script = (ROOT / "deploy" / "cloud-init.sh").read_text()
    for k in ("COURTLISTENER_TOKEN", "VULTR_INFERENCE_API_KEY"):
        if not env.get(k):
            print(f"{k} missing from .env"); return 2
        script = script.replace(f"__{k}__", env[k])
    script = script.replace("__SITE_ADDRESS__", site)

    keys = c.get(f"{API}/ssh-keys").json().get("ssh_keys", [])
    body = {
        "region": region, "plan": plan, "os_id": os_id,
        "label": "cite-checker", "hostname": "cite-checker", "tags": [TAG],
        "user_data": base64.b64encode(script.encode()).decode(),
        "sshkey_id": [k["id"] for k in keys],
        "backups": "disabled", "activation_email": False,
    }
    r = c.post(f"{API}/instances", json=body)
    if r.status_code not in (200, 201, 202):
        print("create failed", r.status_code, r.text); return 1
    inst = r.json()["instance"]
    iid = inst["id"]
    print("created", iid, "default password withheld; ssh keys:", len(keys))

    for _ in range(60):
        time.sleep(10)
        i = c.get(f"{API}/instances/{iid}").json()["instance"]
        print(f"  {i['status']:8} {i['server_status']:10} {i['main_ip']}")
        if i["status"] == "active" and i["main_ip"] != "0.0.0.0":
            print(json.dumps({"id": iid, "ip": i["main_ip"]}))
            print(f"\nthen: watch http://{i['main_ip']}/api/health  (cloud-init takes ~3 min)")
            return 0
    print("timed out waiting for the instance"); return 1


if __name__ == "__main__":
    sys.exit(main())
