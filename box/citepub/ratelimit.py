"""Per-IP rate limiting for the public endpoints. In-memory, no dependencies:
the app runs as a single process on one box, and the point is to keep one
person from monopolising the model and CourtListener quotas, not to be a
distributed limiter.

Two windows per route: a short burst window and a daily one.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

# route prefix -> (per minute, per day)
LIMITS = {
    "/api/check":   (int(os.environ.get("RL_CHECK_MIN", 6)),   int(os.environ.get("RL_CHECK_DAY", 120))),
    "/api/extract": (int(os.environ.get("RL_EXTRACT_MIN", 12)), int(os.environ.get("RL_EXTRACT_DAY", 300))),
}
_lock = threading.Lock()
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def client_ip(headers, fallback: str) -> str:
    # Caddy sets X-Forwarded-For; the app itself is never exposed directly
    xff = headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else fallback


def check(route: str, ip: str) -> tuple[bool, str]:
    """Record a hit and say whether it is allowed. Returns (ok, reason)."""
    lim = next((v for k, v in LIMITS.items() if route.startswith(k)), None)
    if lim is None:
        return True, ""
    per_min, per_day = lim
    now = time.time()
    with _lock:
        q = _hits[(route, ip)]
        while q and q[0] < now - 86400:
            q.popleft()
        minute = sum(1 for t in q if t > now - 60)
        if minute >= per_min:
            return False, f"rate limit: {per_min} per minute from one address; try again in a minute"
        if len(q) >= per_day:
            return False, f"rate limit: {per_day} per day from one address"
        q.append(now)
    return True, ""
