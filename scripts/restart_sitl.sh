#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/run"

# Stop SITL only; leave the HID bridge running if possible.
if [ -f "$RUN/sitl.pid" ]; then
  PID="$(cat "$RUN/sitl.pid")"
  kill "$PID" 2>/dev/null || true
  rm -f "$RUN/sitl.pid"
fi
pkill -f '/inav_SITL' 2>/dev/null || true
sleep 0.5

"$ROOT/scripts/start_sitl.sh"
exit 0
