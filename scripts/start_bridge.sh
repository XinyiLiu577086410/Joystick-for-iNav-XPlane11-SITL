#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "HID config: $ROOT/config/hid2msp_inav.json"
exec python3 "$ROOT/scripts/hid2msp.py" --config "$ROOT/config/hid2msp_inav.json" --port 5762 -v
