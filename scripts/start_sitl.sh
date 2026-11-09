#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/config/runtime"
SITL="/Applications/INAV Configurator 9.0.0.app/Contents/Resources/sitl/macos/inav_SITL"
echo "SITL eeprom: $ROOT/config/runtime/plane.bin"
if [ ! -x "$SITL" ]; then
  echo "SITL not found: $SITL" >&2
  echo "Install INAV Configurator 9.0.0 or edit SITL in this script." >&2
  exit 1
fi
exec "$SITL" --path="$ROOT/config/runtime/plane.bin"
