#!/bin/bash
set -e
cd "$(dirname "$0")"
mkdir -p "$PWD/.sitl"
SITL="/Applications/INAV Configurator 9.0.0.app/Contents/Resources/sitl/macos/inav_SITL"
if [ ! -x "$SITL" ]; then
  echo "SITL not found: $SITL" >&2
  echo "Install INAV Configurator 9.0.0 or edit SITL in this script." >&2
  exit 1
fi
exec "$SITL" --path="$PWD/.sitl/plane.bin"
