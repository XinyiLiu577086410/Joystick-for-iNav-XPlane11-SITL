#!/usr/bin/env python3
"""Run a child process and copy its output to a log with timestamps.

Started in the background by hidctl so SITL/bridge keep running after hidctl
exits, while every line gets a timestamp and the child's exit code is logged.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
kernel32.GetProcessTimes.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def creation_time(pid: int) -> float:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0.0
    try:
        creation = (wintypes.DWORD * 2)()
        exit_time = (wintypes.DWORD * 2)()
        kernel = (wintypes.DWORD * 2)()
        user = (wintypes.DWORD * 2)()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return 0.0
        ticks = (creation[1] << 32) | creation[0]
        return ticks / 10_000_000 - 11_644_473_600
    finally:
        kernel32.CloseHandle(handle)


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--pidfile", required=True)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--", dest="separator", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        return 2

    log_path = Path(args.log)
    pid_path = Path(args.pidfile)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8", errors="replace", buffering=1) as log:
        process = subprocess.Popen(
            command,
            cwd=args.cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
            bufsize=0,
        )

        created = creation_time(process.pid)
        try:
            pid_path.write_text(f"{process.pid}\n{created:.3f}\n")
        except OSError:
            pass

        assert process.stdout is not None
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            log.write(f"{stamp()} {line}\n")

        code = process.wait()
        log.write(f"{stamp()} ===== {Path(command[0]).name} exited code={code} (0x{code & 0xFFFFFFFF:08X}) =====\n")
        try:
            pid_path.unlink()
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
