#!/bin/bash
# national_refresh.sh - keep the nationwide CourtListener index (cl_national.py) current, hands-free.
# Runs weekly (cron). Finds the latest quarter-end bulk snapshot, checks the three files are published, skips if that
# snapshot is already installed (marker national/done-<snapshot>). Otherwise:
#   1. downloads the .bz2 files to national/dl/ with curl -C - (a dropped connection resumes, it never restarts)
#   2. builds new/cl.db and new/cl-text.db with cl_build.py (old files keep serving meanwhile)
#   3. verifies the new files (row counts not smaller than 98% of the old ones, a known case resolves and its text reads)
#   4. swaps them in (READY off -> move -> READY on), restarts the public page, deletes the downloads
# Anything failing leaves the old files in place and tries again next week. Needs ~120 GB free while it runs.
set -u
D=/opt/banksy/lex/national; LOG=$D/refresh.log; PY=/opt/banksy/lex/venv/bin/python
BASE="https://com-courtlistener-storage.s3-us-west-2.amazonaws.com/bulk-data"
log(){ echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG"; }
exec 8>"$D/.refresh.lock"; flock -n 8 || { log "a refresh is already running"; exit 0; }
SNAP=${1:-$(python3 -c "
import datetime as d
t=d.date.today(); q=[d.date(t.year-1,12,31),d.date(t.year,3,31),d.date(t.year,6,30),d.date(t.year,9,30),d.date(t.year,12,31)]
print(max(x for x in q if x<=t))")}
[ -f "$D/done-$SNAP" ] && { log "snapshot $SNAP already installed; nothing to do"; exit 0; }
for f in citations opinion-clusters opinions; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -I "$BASE/$f-$SNAP.csv.bz2")
  [ "$code" = "200" ] || { log "snapshot $SNAP not published yet ($f -> HTTP $code); retry next week"; exit 0; }
done
free_gb=$(df -BG --output=avail "$D" | tail -1 | tr -dc 0-9)
[ "$free_gb" -ge 130 ] || { log "only ${free_gb} GB free under $D; need 130 - not starting"; exit 1; }
log "snapshot $SNAP is published; refreshing the nationwide index"
mkdir -p "$D/dl" "$D/new"; rm -f "$D/new/"*
for f in citations opinion-clusters opinions; do
  ok=0
  for try in $(seq 1 60); do
    curl -sS -f -C - --retry 3 --retry-delay 10 -o "$D/dl/$f-$SNAP.csv.bz2" "$BASE/$f-$SNAP.csv.bz2" && { ok=1; break; }
    log "download of $f interrupted (try $try); resuming in 60s"; sleep 60
  done
  [ $ok = 1 ] || { log "could not download $f after 60 tries; old index stays; retry next week"; exit 1; }
  want=$(curl -sI "$BASE/$f-$SNAP.csv.bz2" | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}')
  [ "$(stat -c %s "$D/dl/$f-$SNAP.csv.bz2")" = "$want" ] || { log "$f size mismatch after download; removing it; retry next week"; rm -f "$D/dl/$f-$SNAP.csv.bz2"; exit 1; }
done
log "downloads complete; building"
UNZ="bzip2 -dc"; command -v lbzip2 >/dev/null && UNZ="lbzip2 -dc"
W=$(( $(nproc) / 4 )); [ $W -lt 2 ] && W=2
step(){ # step <file> <cl_build args...>  - fails if either the decompressor or the builder fails
  local f=$1; shift
  nice -n 10 $UNZ "$D/dl/$f-$SNAP.csv.bz2" | nice -n 10 $PY "$D/cl_build.py" "$@" 2>>"$LOG"
  local rc=("${PIPESTATUS[@]}"); [ "${rc[0]}" = 0 ] && [ "${rc[1]}" = 0 ]
}
step citations citations --out "$D/new/cl.db" \
 && step opinion-clusters clusters --out "$D/new/cl.db" --date "$SNAP" \
 && step opinions text --out "$D/new/cl-text.db" --date "$SNAP" --workers $W \
 || { log "build failed (see above); old index stays; retry next week"; exit 1; }
$PY - "$D" "$SNAP" >>"$LOG" 2>&1 <<'PY' || { log "new files FAILED verification; old index stays"; exit 1; }
import sqlite3, sys, os
from compression import zstd
D, snap = sys.argv[1], sys.argv[2]
def meta(p):
    if not os.path.exists(p): return {}
    c = sqlite3.connect("file:%s?mode=ro" % p, uri=True); m = dict(c.execute("select k, v from meta").fetchall()); c.close(); return m
ni, nt = meta(D + "/new/cl.db"), meta(D + "/new/cl-text.db")
assert ni.get("index_date") == snap and nt.get("text_date") == snap, "new files are not marked complete"
i = sqlite3.connect("file:%s/new/cl.db?mode=ro" % D, uri=True); t = sqlite3.connect("file:%s/new/cl-text.db?mode=ro" % D, uri=True)
nc = i.execute("select count(*) from clusters").fetchone()[0]; nx = i.execute("select count(*) from citations").fetchone()[0]; nr = int(nt["text_rows"])
oc = ox = orr = 0
if os.path.exists(D + "/cl.db"):
    o = sqlite3.connect("file:%s/cl.db?mode=ro" % D, uri=True); oc = o.execute("select count(*) from clusters").fetchone()[0]; ox = o.execute("select count(*) from citations").fetchone()[0]
    orr = int(meta(D + "/cl-text.db").get("text_rows") or 0)
print("new: clusters %d citations %d texts %d | old: %d %d %d" % (nc, nx, nr, oc, ox, orr))
assert nc >= 0.98 * oc and nx >= 0.98 * ox and nr >= 0.98 * orr, "new snapshot is smaller than the installed one"
r = i.execute("select c.id from citations x join clusters c on c.id = x.cluster_id where x.volume='550' and x.page='544' and replace(x.reporter,' ','')='U.S.'").fetchall()
assert r, "550 U.S. 544 does not resolve"
b = t.execute("select text from opinions where cluster_id = ?", (r[0][0],)).fetchone()
assert b and "plausible on its face" in zstd.decompress(b[0]).decode(), "Twombly text does not read"
print("VERIFY OK")
PY
log "verified; swapping in $SNAP"
rm -f "$D/READY"
mkdir -p "$D/old"; mv -f "$D/cl.db" "$D/cl-text.db" "$D/old/" 2>/dev/null
mv -f "$D/new/cl.db" "$D/new/cl-text.db" "$D/" && chmod 644 "$D/cl.db" "$D/cl-text.db" && touch "$D/READY" \
  || { log "SWAP FAILED - restoring the old files"; mv -f "$D/old/"* "$D/"; touch "$D/READY"; exit 1; }
sudo -n systemctl restart citepub 2>>"$LOG" || log "could not restart citepub (it will pick the new files up on its next restart)"
sleep 5
if /opt/banksy/lex/citepub/smoke.sh >>"$LOG" 2>&1; then
  date > "$D/done-$SNAP"; rm -rf "$D/old" "$D/dl" "$D/new"; log "NATIONAL_REFRESH_DONE snapshot=$SNAP"
else
  log "smoke test failed on the new files - rolling back"; rm -f "$D/READY"; mv -f "$D/old/"* "$D/"; touch "$D/READY"; sudo -n systemctl restart citepub; exit 1
fi
