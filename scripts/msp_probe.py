#!/usr/bin/env python3
"""MSP v1 probe for INAV SITL.

Reads live values from a SITL UART over TCP without Configurator, or injects
raw RC frames.  Only one TCP client per UART is allowed, so pick an idle port
(5760 while Configurator is closed, 5761 while the HITL plugin is disconnected).

Examples:
    python scripts/msp_probe.py --port 5760
    python scripts/msp_probe.py --port 5760 --watch
    python scripts/msp_probe.py --port 5762 --rc 1500,1500,1000,1500 --count 50
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time

MSP_API_VERSION = 1
MSP_FC_VERSION = 3
MSP_STATUS = 101
MSP_RC = 105
MSP_ATTITUDE = 108
MSP_ANALOG = 110
MSP_BOXIDS = 119
MSP_MODE_RANGES = 34
MSP_SET_RAW_RC = 200


def frame(cmd: int, payload: bytes = b"") -> bytes:
    body = bytes((len(payload), cmd)) + payload
    checksum = 0
    for byte in body:
        checksum ^= byte
    return b"$M<" + body + bytes((checksum,))


def read_frame(sock: socket.socket, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    buffer = b""
    while time.monotonic() < deadline:
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buffer += chunk
        start = buffer.find(b"$M>")
        if start < 0:
            buffer = buffer[-4:]
            continue
        if len(buffer) < start + 5:
            continue
        length = buffer[start + 3]
        total = start + 5 + length
        if len(buffer) < total:
            continue
        return buffer[start + 4], buffer[start + 5:start + 5 + length]
    return None


def request(sock, cmd: int, payload: bytes = b""):
    sock.sendall(frame(cmd, payload))
    return read_frame(sock)


def decode_status(payload: bytes) -> dict:
    cycle, i2c, sensors, flags, profile = struct.unpack("<HHHIB", payload[:11])
    return {
        "cycle_time_us": cycle,
        "i2c_errors": i2c,
        "sensors": sensors,
        "flight_mode_flags": f"0x{flags:08X}",
        "profile": profile,
    }


def decode_rc(payload: bytes):
    count = len(payload) // 2
    return list(struct.unpack("<%dH" % count, payload[:count * 2]))


def decode_attitude(payload: bytes) -> dict:
    roll, pitch, yaw = struct.unpack("<hhh", payload[:6])
    return {"roll": roll / 10.0, "pitch": pitch / 10.0, "yaw": yaw / 10.0}


def main() -> int:
    parser = argparse.ArgumentParser(description="MSP probe for INAV SITL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5760)
    parser.add_argument("--watch", action="store_true", help="print RC/attitude once per second")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--rc", default=None, help="comma-separated 16 PWM values to send")
    parser.add_argument("--count", type=int, default=50, help="RC frames to send (default 50)")
    parser.add_argument("--rate", type=float, default=50.0, help="RC frame rate (default 50 Hz)")
    args = parser.parse_args()

    try:
        sock = socket.create_connection((args.host, args.port), timeout=3)
    except OSError as exc:
        print(f"cannot connect to {args.host}:{args.port}: {exc}", file=sys.stderr)
        print("hint: one TCP client per UART; close Configurator/plugin on that port first", file=sys.stderr)
        return 2

    try:
        if args.rc:
            values = [int(item) for item in args.rc.split(",")]
            values = (values + [1500] * 16)[:16]
            payload = struct.pack("<16H", *values)
            period = 1.0 / max(1.0, args.rate)
            for _ in range(max(1, args.count)):
                sock.sendall(frame(MSP_SET_RAW_RC, payload))
                time.sleep(period)
            print(f"sent {args.count} SET_RAW_RC frames: {values}")
            return 0

        if args.watch:
            while True:
                rc = request(sock, MSP_RC)
                att = request(sock, MSP_ATTITUDE)
                line = ""
                if rc:
                    line += "rc=" + " ".join(str(v) for v in decode_rc(rc[1])[:9])
                if att:
                    a = decode_attitude(att[1])
                    line += f"  att roll={a['roll']:+.1f} pitch={a['pitch']:+.1f} yaw={a['yaw']:+.1f}"
                print(line)
                time.sleep(1.0)

        info: dict = {}
        result = request(sock, MSP_API_VERSION)
        if result:
            info["api_version"] = list(result[1][:3])
        result = request(sock, MSP_FC_VERSION)
        if result and len(result[1]) >= 3:
            info["fc_version"] = list(result[1][:3])
        result = request(sock, MSP_STATUS)
        if result:
            info["status"] = decode_status(result[1])
        result = request(sock, MSP_RC)
        if result:
            info["rc"] = decode_rc(result[1])
        result = request(sock, MSP_ATTITUDE)
        if result:
            info["attitude"] = decode_attitude(result[1])
        result = request(sock, MSP_BOXIDS)
        if result:
            info["box_ids"] = list(result[1])
        result = request(sock, MSP_MODE_RANGES)
        if result:
            ranges = []
            payload = result[1]
            for index in range(0, len(payload) - 3, 4):
                box_id, aux, start, end = payload[index:index + 4]
                if box_id == 0 and aux == 0 and start == 0 and end == 0:
                    continue
                ranges.append(
                    {
                        "box": box_id,
                        "aux_channel": aux + 5,
                        "start": 900 + start * 25,
                        "end": 900 + end * 25,
                    }
                )
            info["mode_ranges"] = ranges

        if not info:
            print("no MSP response (port busy, wrong UART, or SITL not running)", file=sys.stderr)
            return 1

        if args.as_json:
            print(json.dumps(info, indent=2))
        else:
            for key, value in info.items():
                print(f"{key}: {value}")
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
