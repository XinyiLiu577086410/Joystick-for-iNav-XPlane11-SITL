"""Windows process manager using Win32 APIs and taskkill."""

from __future__ import annotations

import csv
import ctypes
import io
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ...models import ProcessHandle, ProcessSpec

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
]
kernel32.GetProcessTimes.restype = wintypes.BOOL


def _open_process(pid: int, access: int) -> Optional[int]:
    handle = kernel32.OpenProcess(access, False, pid)
    return handle or None


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_image(pid: int) -> Optional[Path]:
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(4096)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value)
        return None
    finally:
        kernel32.CloseHandle(handle)


def process_creation_time(pid: int) -> Optional[float]:
    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return None
    try:
        creation = FILETIME()
        exit_time = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return None
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return ticks / 10_000_000 - 11_644_473_600
    finally:
        kernel32.CloseHandle(handle)


def _run_hidden(argv: List[str]) -> str:
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    return result.stdout


@dataclass
class Win32ProcessManager:
    creation_tolerance: float = 3.0
    _spawned: list = field(default_factory=list)
    _procs: dict = field(default_factory=dict)

    def spawn(self, spec: ProcessSpec) -> ProcessHandle:
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = None
        if spec.env:
            env = dict(os.environ)
            env.update(spec.env)
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if spec.detached else 0
        with spec.log_path.open("ab") as log:
            proc = subprocess.Popen(
                list(spec.argv),
                cwd=str(spec.cwd),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
        created = process_creation_time(proc.pid) or 0.0
        deadline = time.monotonic() + 1.0
        while created == 0.0 and time.monotonic() < deadline:
            time.sleep(0.02)
            created = process_creation_time(proc.pid) or 0.0
        handle = ProcessHandle(pid=proc.pid, start_time=created, exe=Path(spec.argv[0]).name)
        self._spawned.append(handle)
        self._procs[proc.pid] = proc
        return handle

    def stop(self, handle: ProcessHandle) -> None:
        proc = self._procs.pop(handle.pid, None)
        if not self.is_alive(handle):
            if proc is not None:
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
            return
        subprocess.run(
            ["taskkill", "/PID", str(handle.pid), "/T", "/F"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc is not None:
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass

    def is_alive(self, handle: ProcessHandle) -> bool:
        if not process_exists(handle.pid):
            return False
        if handle.start_time:
            actual = process_creation_time(handle.pid)
            if actual is None or abs(actual - handle.start_time) > self.creation_tolerance:
                return False
        return True

    def find(self, name: str) -> List[ProcessHandle]:
        try:
            reader = csv.reader(io.StringIO(_run_hidden(["tasklist", "/FO", "CSV", "/NH"])))
        except OSError:
            return []
        needle = name.casefold()
        result: List[ProcessHandle] = []
        for row in reader:
            if len(row) < 2 or not row[1].strip().isdigit():
                continue
            image = row[0].strip().strip('"')
            if needle not in image.casefold():
                continue
            pid = int(row[1])
            created = process_creation_time(pid) or 0.0
            result.append(ProcessHandle(pid=pid, start_time=created, exe=image))
        return result

    def port_listening(self, port: int) -> bool:
        output = _run_hidden(["netstat", "-ano", "-p", "tcp"])
        suffix = f":{port}"
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[0].upper() != "TCP":
                continue
            if parts[1].endswith(suffix) and parts[3].upper() == "LISTENING":
                return True
        return False
