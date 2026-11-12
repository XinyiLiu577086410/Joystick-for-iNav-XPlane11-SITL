"""Shared POSIX process manager for macOS and Linux."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ...models import ProcessHandle, ProcessSpec


def _ps_start_time(pid: int) -> float:
    try:
        output = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout.strip()
    except OSError:
        return 0.0
    if not output:
        return 0.0
    try:
        return datetime.strptime(output, "%a %b %d %H:%M:%S %Y").timestamp()
    except ValueError:
        return 0.0


def _linux_start_time(pid: int) -> float:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        boot = 0.0
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("btime "):
                boot = float(line.split()[1])
                break
        rest = stat.rsplit(")", 1)[1].split()
        ticks = float(rest[19])
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return 0.0


def process_start_time(pid: int) -> float:
    if sys.platform.startswith("linux"):
        return _linux_start_time(pid)
    if sys.platform == "darwin":
        return _ps_start_time(pid)
    return 0.0


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@dataclass
class PosixProcessManager:
    creation_tolerance: float = 3.0
    _procs: dict = field(default_factory=dict)

    def spawn(self, spec: ProcessSpec) -> ProcessHandle:
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = None
        if spec.env:
            env = dict(os.environ)
            env.update(spec.env)
        with spec.log_path.open("ab") as log:
            proc = subprocess.Popen(
                list(spec.argv),
                cwd=str(spec.cwd),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=spec.detached,
            )
        created = process_start_time(proc.pid)
        handle = ProcessHandle(pid=proc.pid, start_time=created, exe=Path(spec.argv[0]).name)
        self._procs[proc.pid] = proc
        return handle

    def stop(self, handle: ProcessHandle) -> None:
        proc = self._procs.pop(handle.pid, None)
        if not self.is_alive(handle):
            if proc is not None:
                proc.wait()
            return
        try:
            os.killpg(handle.pid, signal.SIGTERM)
        except OSError:
            try:
                os.kill(handle.pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and process_exists(handle.pid):
            time.sleep(0.05)
        if process_exists(handle.pid):
            try:
                os.killpg(handle.pid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(handle.pid, signal.SIGKILL)
                except OSError:
                    pass
        if proc is not None:
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass

    def is_alive(self, handle: ProcessHandle) -> bool:
        if not process_exists(handle.pid):
            return False
        if handle.start_time:
            actual = process_start_time(handle.pid)
            if actual and abs(actual - handle.start_time) > self.creation_tolerance:
                return False
        return True

    def find(self, name: str) -> List[ProcessHandle]:
        try:
            output = subprocess.run(
                ["ps", "-axo", "pid=,comm="],
                capture_output=True,
                text=True,
                errors="replace",
            ).stdout
        except OSError:
            return []
        needle = name.casefold()
        result: List[ProcessHandle] = []
        for line in output.splitlines():
            match = re.match(r"\s*(\d+)\s+(.+)", line)
            if not match:
                continue
            pid = int(match.group(1))
            command = match.group(2)
            if needle not in command.casefold():
                continue
            result.append(
                ProcessHandle(
                    pid=pid,
                    start_time=process_start_time(pid),
                    exe=Path(command).name,
                )
            )
        return result

    def port_listening(self, port: int) -> bool:
        if sys.platform == "darwin":
            try:
                output = subprocess.run(
                    ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                    capture_output=True,
                    text=True,
                    errors="replace",
                ).stdout
                return bool(output.strip())
            except OSError:
                return False
        try:
            output = subprocess.run(
                ["ss", "-ltn"],
                capture_output=True,
                text=True,
                errors="replace",
            ).stdout
        except OSError:
            return False
        return any(re.search(rf":{port}\b", line) for line in output.splitlines())
