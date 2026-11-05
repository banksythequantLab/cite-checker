"""The only door out of the app network: an HTTP CONNECT proxy that allows
exactly the hostnames in EGRESS_ALLOW (port 443 only) and refuses everything
else -- by hostname, so CloudFront's rotating IPs don't matter. Every refusal
is logged as a JSON line; a blocked attempt must be visible, never silent.

The app network itself is a Docker `internal` bridge: the kernel gives it no
route off the host. Even if the app ignored this proxy, it could reach nothing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

ALLOW = {h.strip().lower() for h in os.environ.get("EGRESS_ALLOW", "").split(",") if h.strip()}
PORT = int(os.environ.get("PORT", "3128"))


def log(**kv):
    kv["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sys.stdout.write(json.dumps(kv) + "\n"); sys.stdout.flush()


async def pump(r: asyncio.StreamReader, w: asyncio.StreamWriter):
    try:
        while (b := await r.read(65536)):
            w.write(b); await w.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try: w.close()
        except Exception: pass


async def handle(r: asyncio.StreamReader, w: asyncio.StreamWriter):
    peer = w.get_extra_info("peername")
    try:
        line = (await asyncio.wait_for(r.readline(), 10)).decode("latin1").strip()
        while (await r.readline()).strip():   # drain request headers
            pass
        parts = line.split()
        if len(parts) != 3 or parts[0] != "CONNECT" or ":" not in parts[1]:
            log(event="refused", reason="not a CONNECT", request=line[:120], src=peer[0])
            w.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
            await w.drain(); w.close(); return
        host, port = parts[1].rsplit(":", 1)
        host = host.lower()
        if host not in ALLOW or port != "443":
            log(event="refused", reason="not on the allow-list", host=host, port=port, src=peer[0])
            w.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await w.drain(); w.close(); return
        try:
            ur, uw = await asyncio.wait_for(asyncio.open_connection(host, int(port)), 15)
        except Exception as e:
            log(event="upstream_failed", host=host, error=str(e)[:120], src=peer[0])
            w.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await w.drain(); w.close(); return
        log(event="allowed", host=host, port=port, src=peer[0])
        w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n"); await w.drain()
        await asyncio.gather(pump(r, uw), pump(ur, w))
    except Exception as e:
        log(event="error", error=str(e)[:120], src=peer[0] if peer else None)
        try: w.close()
        except Exception: pass


async def main():
    log(event="start", allow=sorted(ALLOW), port=PORT)
    srv = await asyncio.start_server(handle, "0.0.0.0", PORT)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
