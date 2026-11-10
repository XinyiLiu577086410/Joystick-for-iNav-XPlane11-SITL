#!/usr/bin/env python3
"""TCP tap between the X-Plane HITL plugin and a shifted INAV SITL port.

The plugin always connects to 127.0.0.1:5761.  Start SITL with
`--tcpbaseport 5860` so its UART2 listens on 5861, then run:

    python scripts/msp_tap.py --listen-port 5761 --target-port 5861

Every MSP frame in both directions is written to the log with a timestamp,
the command id and the payload (SET_RAW_RC channels are decoded).
"""

from __future__ import annotations

import argparse
import datetime
import socket
import struct
import sys
import threading

COMMANDS = {
    1: "MSP_API_VERSION",
    3: "MSP_FC_VERSION",
    44: "MSP_RX_CONFIG",
    101: "MSP_STATUS",
    105: "MSP_RC",
    108: "MSP_ATTITUDE",
    110: "MSP_ANALOG",
    119: "MSP_BOXIDS",
    200: "MSP_SET_RAW_RC",
    0x201F: "MSP_SIMULATOR",
    0x2000: "MSP2_INAV_STATUS",
}


def stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def describe(cmd: int, payload: bytes) -> str:
    name = COMMANDS.get(cmd, f"cmd_{cmd}")
    extra = ""
    if cmd == 200 and len(payload) >= 32:
        channels = struct.unpack("<16H", payload[:32])
        extra = " ch=" + " ".join(str(v) for v in channels[:9])
    return f"{name}({cmd}) len={len(payload)}{extra}"


def extract_frames(buffer: bytes):
    """Yield (direction, cmd, payload) for complete MSP v1/v2 frames."""
    frames = []
    index = 0
    while True:
        starts = [(buffer.find(b"$M<", index), "C>S"), (buffer.find(b"$M>", index), "S>C")]
        starts += [(buffer.find(b"$X<", index), "C>S"), (buffer.find(b"$X>", index), "S>C")]
        starts = [(pos, direction) for pos, direction in starts if pos >= 0]
        if not starts:
            return frames, b""
        pos, direction = min(starts, key=lambda item: item[0])
        if buffer[pos + 1:pos + 2] == b"M":
            if len(buffer) < pos + 5:
                return frames, buffer[pos:]
            length = buffer[pos + 3]
            total = pos + 5 + length
            if len(buffer) < total:
                return frames, buffer[pos:]
            cmd = buffer[pos + 4]
            payload = buffer[pos + 5:pos + 5 + length]
            frames.append((direction, cmd, payload))
            index = total
        else:
            if len(buffer) < pos + 8:
                return frames, buffer[pos:]
            cmd = struct.unpack("<H", buffer[pos + 4:pos + 6])[0]
            length = struct.unpack("<H", buffer[pos + 6:pos + 8])[0]
            total = pos + 9 + length
            if len(buffer) < total:
                return frames, buffer[pos:]
            payload = buffer[pos + 8:pos + 8 + length]
            frames.append((direction, cmd, payload))
            index = total


def main() -> int:
    parser = argparse.ArgumentParser(description="MSP tap for plugin <-> SITL")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=5761)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=5861)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    log = open(args.log, "a", encoding="utf-8", buffering=1)
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(1)
    print(f"tap listening on {args.listen_port}, forwarding to {args.target_port}", flush=True)
    log.write(f"{stamp()} tap start {args.listen_port} -> {args.target_port}\n")

    client, address = server.accept()
    print(f"plugin connected from {address}", flush=True)
    upstream = socket.create_connection((args.target_host, args.target_port), timeout=5)

    lock = threading.Lock()
    done = threading.Event()

    def pump(source: socket.socket, sink: socket.socket, direction: str) -> None:
        buffer = b""
        try:
            while True:
                data = source.recv(4096)
                if not data:
                    break
                sink.sendall(data)
                buffer += data
                frames, buffer = extract_frames(buffer)
                with lock:
                    for frame_direction, cmd, payload in frames:
                        log.write(
                            f"{stamp()} {frame_direction} {describe(cmd, payload)} "
                            f"data={payload[:64].hex()}\n"
                        )
        except OSError:
            pass
        finally:
            done.set()
            log.write(f"{stamp()} {direction} closed\n")

    threading.Thread(target=pump, args=(client, upstream, "C>S"), daemon=True).start()
    threading.Thread(target=pump, args=(upstream, client, "S>C"), daemon=True).start()

    done.wait()
    try:
        client.close()
    except OSError:
        pass
    try:
        upstream.close()
    except OSError:
        pass
    server.close()
    log.write(f"{stamp()} tap stop\n")
    log.close()
    print("tap stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
