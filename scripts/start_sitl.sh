#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/run"
LOG="$ROOT/logs"
mkdir -p "$RUN" "$LOG" "$ROOT/config/runtime"

PIDFILE="$RUN/sitl.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi

SITL="/Applications/INAV Configurator 9.0.0.app/Contents/Resources/sitl/macos/inav_SITL"
if [ ! -x "$SITL" ]; then
  echo "SITL not found: $SITL" >"$LOG/sitl.log"
  exit 1
fi

nohup "$SITL" --path="$ROOT/config/runtime/plane.bin" >"$LOG/sitl.log" 2>&1 &
echo $! >"$PIDFILE"
disown "$(cat "$PIDFILE")" 2>/dev/null || true
exit 0
