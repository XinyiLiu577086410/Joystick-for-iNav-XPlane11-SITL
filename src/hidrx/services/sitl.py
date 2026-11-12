"""SITL process lifecycle."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..models import InavSelection, ProcessHandle, ProcessSpec
from ..platform.base import Paths, ProcessManager

if TYPE_CHECKING:
    from .inav import InavService


class SitlError(RuntimeError):
    pass


@dataclass
class SitlService:
    process: ProcessManager
    paths: Paths
    inav: "InavService"
    base_port: int = 5760

    def command(self, selection: InavSelection) -> tuple:
        return (
            str(selection.install.path),
            f"--path={selection.eeprom}",
            f"--tcpbaseport={self.base_port}",
        )

    def start(self, selection: InavSelection, timeout: float = 10.0) -> ProcessHandle:
        self.inav.ensure_eeprom(selection)
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        handle = self.process.spawn(
            ProcessSpec(
                argv=self.command(selection),
                cwd=self.paths.repo_root,
                log_path=self.paths.logs_dir / "sitl.log",
            )
        )
        self.wait_ready(handle, timeout)
        return handle

    def wait_ready(self, handle: ProcessHandle, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        ports = tuple(self.base_port + offset for offset in range(4))
        while time.monotonic() < deadline:
            if not self.process.is_alive(handle):
                raise SitlError(
                    f"inav_SITL exited during startup; see {self.paths.logs_dir / 'sitl.log'}"
                )
            if all(self.process.port_listening(port) for port in ports):
                return
            time.sleep(0.1)
        raise SitlError(f"SITL ports {ports} did not open within {timeout:.1f}s")

    def stop(self, handle: ProcessHandle) -> None:
        self.process.stop(handle)
