"""MSP v1 framing and a minimal TX link."""

from __future__ import annotations

import socket
import struct
from typing import Optional, Sequence

from ..constants import MSP_SET_RAW_RC


class MspError(RuntimeError):
    pass


def msp_v1_frame(command: int, payload: bytes = b"") -> bytes:
    if not 0 <= command <= 0xFF:
        raise ValueError("MSP v1 command must be 0..255")
    if len(payload) > 0xFF:
        raise ValueError("MSP v1 payload too large")
    body = bytes((len(payload), command)) + payload
    checksum = 0
    for byte in body:
        checksum ^= byte
    return b"$M<" + body + bytes((checksum,))


def set_raw_rc_frame(channels: Sequence[int]) -> bytes:
    payload = struct.pack("<%dH" % len(channels), *channels)
    return msp_v1_frame(MSP_SET_RAW_RC, payload)


class MspLink:
    """TCP link to one SITL UART configured as MSP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5762, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.last_error: Optional[str] = None

    def connect(self) -> bool:
        self.close()
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock.settimeout(self.timeout)
            self.last_error = None
            return True
        except OSError as exc:
            self.last_error = str(exc)
            self.sock = None
            return False

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def send(self, frame: bytes) -> bool:
        if self.sock is None:
            return False
        try:
            self.sock.sendall(frame)
            return True
        except OSError as exc:
            self.last_error = str(exc)
            self.close()
            return False

    def send_raw_rc(self, channels: Sequence[int]) -> bool:
        return self.send(set_raw_rc_frame(channels))
