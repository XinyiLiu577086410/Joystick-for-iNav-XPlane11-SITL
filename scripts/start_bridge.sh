#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/run"
LOG="$ROOT/logs"
mkdir -p "$RUN" "$LOG"

PIDFILE="$RUN/bridge.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi

nohup python3 "$ROOT/scripts/hid2msp.py" \
  --config "$ROOT/config/hid2msp_inav.json" \
  --port 5762 -v >"$LOG/bridge.log" 2>&1 &
echo $! >"$PIDFILE"
disown "$(cat "$PIDFILE")" 2>/dev/null || true
exit 0
