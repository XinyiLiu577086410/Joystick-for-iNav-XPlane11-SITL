#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/logs"
mkdir -p "$LOG"

if pgrep -f '/X-Plane.app/Contents/MacOS/X-Plane' >/dev/null 2>&1; then
  exit 0
fi

XP_APP="${XP_APP:-$HOME/Applications/X-Plane 11.app}"
if [ -d "$XP_APP" ]; then
  open "$XP_APP" >"$LOG/xplane.log" 2>&1 || true
else
  open "steam://run/269950" >"$LOG/xplane.log" 2>&1 || true
fi
exit 0
