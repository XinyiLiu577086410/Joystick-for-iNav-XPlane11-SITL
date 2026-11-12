"""Platform interfaces.  Core code depends only on these Protocols."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Protocol

from ..models import (
    InavInstall,
    KeyboardCapabilities,
    PluginInfo,
    ProcessHandle,
    ProcessInfo,
    ProcessSpec,
    XPlaneInfo,
)


class ProcessManager(Protocol):
    def spawn(self, spec: ProcessSpec) -> ProcessHandle: ...

    def stop(self, handle: ProcessHandle) -> None: ...

    def is_alive(self, handle: ProcessHandle) -> bool: ...

    def find(self, name: str) -> List[ProcessHandle]: ...

    def port_listening(self, port: int) -> bool: ...


class KeyboardBackend(Protocol):
    platform: str
    backend: str

    def available(self) -> bool: ...

    def capabilities(self) -> KeyboardCapabilities: ...

    def foreground_matches(self, target: str) -> bool: ...

    def validate(self, binding: str) -> None: ...

    def is_down(self, binding: str) -> bool: ...

    def capture(self, timeout: float) -> Optional[str]: ...


class XPlaneBackend(Protocol):
    def locate(self) -> Optional[XPlaneInfo]: ...

    def running(self) -> Optional[ProcessInfo]: ...

    def plugin(self, aircraft: str) -> Optional[PluginInfo]: ...


class InavLocator(Protocol):
    def discover(self) -> List[InavInstall]: ...

    def resolve_path(self, path: Path) -> Optional[InavInstall]: ...


class Paths(Protocol):
    repo_root: Path
    config_dir: Path
    runtime_dir: Path
    logs_dir: Path
    run_dir: Path


class Platform(Protocol):
    id: str
    process: ProcessManager
    keyboard: KeyboardBackend
    xplane: XPlaneBackend
    inav: InavLocator
    paths: Paths
