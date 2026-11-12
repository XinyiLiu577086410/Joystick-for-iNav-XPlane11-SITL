"""INAV CLI-over-TCP helper for config load."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


class CliError(RuntimeError):
    pass


@dataclass(frozen=True)
class CliResult:
    sent: int
    errors: List[str]
    output: str


def read_commands(path: Path) -> List[str]:
    commands: List[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            commands.append(stripped)
    return commands


def run_cli(
    commands: Sequence[str],
    port: int = 5760,
    host: str = "127.0.0.1",
    save: bool = True,
    timeout: float = 5.0,
) -> CliResult:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise CliError(f"cannot connect to {host}:{port}: {exc}") from exc
    sock.settimeout(0.2)
    output = bytearray()

    def drain() -> None:
        while True:
            try:
                chunk = sock.recv(8192)
            except (socket.timeout, OSError):
                return
            if not chunk:
                return
            output.extend(chunk)

    try:
        sock.sendall(b"#")
        time.sleep(0.3)
        drain()
        for command in commands:
            sock.sendall(command.encode() + b"\r\n")
            time.sleep(0.012)
            drain()
        time.sleep(0.2)
        drain()
        if save:
            sock.sendall(b"save\r\n")
            time.sleep(0.4)
            drain()
    finally:
        try:
            sock.close()
        except OSError:
            pass

    text = output.decode("utf-8", errors="replace")
    errors = [
        line.strip()
        for line in text.splitlines()
        if not line.strip().startswith("#")
        and any(marker in line for marker in ("nknown", "nvalid", "rror", "ailed"))
    ]
    return CliResult(sent=len(commands), errors=errors, output=text)
