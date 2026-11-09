#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/run"

for name in bridge sitl; do
  PIDFILE="$RUN/$name.pid"
  if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE")"
    if kill -0 "$PID" 2>/dev/null; then
      kill "$PID" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
  fi
done

# Best-effort cleanup if PID files are stale/missing.
pkill -f "$ROOT/scripts/hid2msp.py" 2>/dev/null || true
pkill -f '/inav_SITL' 2>/dev/null || true
exit 0
