#!/bin/bash
# install_national.sh - one-time setup of the nationwide half of the citation checker on a box.
# The update channel delivers the code (cite_check.py, cl_national.py, national/*). It cannot deliver the data: the
# index and opinion texts are ~55 GB and are built on the box itself from CourtListener's public bulk dumps.
# This script: 1) adds the weekly refresh to cron, 2) with --build, starts the first build now in the background
# (several hours; needs ~130 GB free under /opt/banksy/lex/national). Until the build finishes and writes
# national/READY, the checker simply works as before, on the box's own New York library. Safe to run again.
set -u
D=/opt/banksy/lex/national; mkdir -p "$D"; chmod +x "$D/cl_build.py" "$D/national_refresh.sh" 2>/dev/null
LINE="0 3 * * 2 $D/national_refresh.sh >> $D/refresh_cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v national_refresh; echo "$LINE" ) | crontab -
echo "cron installed: $LINE"
if [ -f "$D/READY" ]; then echo "nationwide index already installed: $(ls $D/done-* 2>/dev/null | tail -1)"; exit 0; fi
if [ "${1:-}" = "--build" ]; then
  nohup "$D/national_refresh.sh" >> "$D/refresh_cron.log" 2>&1 &
  echo "first build started in the background; follow it with: tail -f $D/refresh.log"
else
  echo "no nationwide data yet. Start the first build now with:  $0 --build   (or wait for Tuesday 3 AM)"
fi
