#!/bin/bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/run"

if pgrep -f '/X-Plane.app/Contents/MacOS/X-Plane' >/dev/null 2>&1; then
  echo "xplane: running"
else
  echo "xplane: not running"
fi

for name in sitl bridge; do
  PIDFILE="$RUN/$name.pid"
  if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE")"
    if kill -0 "$PID" 2>/dev/null; then
      echo "$name: running (pid $PID)"
      continue
    fi
  fi
  echo "$name: not running"
done

for p in 5760 5761 5762 5763; do
  if nc -z -G 1 127.0.0.1 "$p" 2>/dev/null; then
    echo "port $p: open"
  else
    echo "port $p: closed"
  fi
done
