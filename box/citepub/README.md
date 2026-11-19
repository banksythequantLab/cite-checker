# citepub — public page for the box's citation checker

cite.nota.lawyer → Cloudflare tunnel → 127.0.0.1:8124 → `app.py` → `/opt/banksy/lex/cite_check.py`

- One engine. The public page and LEX > CITES on the panel run the same `cite_check.py`: Lex (New York + 2d Cir.,
  PostgreSQL) first, then the nationwide CourtListener index in `/opt/banksy/lex/national` (`cl_national.py`).
- Sealed. `citepub.service` runs as a throwaway user with all of `/opt/banksy` hidden except `lex/` (read-only),
  no capabilities, and a firewall that allows loopback only. Matters, mail, secrets and the NAS are not visible to it.
- Nothing stored. Briefs are checked in memory. Rate limits are per visitor address (`ratelimit.py`).

Service unit: `citepub.service` (copy to /etc/systemd/system). Tunnel: `citepub-tunnel.service`. Remove: `sudo systemctl disable --now citepub citepub-tunnel`.
