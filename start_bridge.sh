#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "HID config: $PWD/hid2msp_xiaoweng.json"
exec python3 hid2msp.py --config hid2msp_xiaoweng.json --port 5762 -v
