"""In-memory platform used by core tests and early service wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..models import (
    InavInstall,
    KeyboardCapabilities,
    PluginInfo,
    ProcessHandle,
    ProcessInfo,
    ProcessSpec,
    XPlaneInfo,
)


@dataclass
class FakePaths:
    repo_root: Path = Path(".")
    config_dir: Path = Path("config")
    runtime_dir: Path = Path("config/runtime")
    logs_dir: Path = Path("logs")
    run_dir: Path = Path("run")


@dataclass
class FakeProcessManager:
    spawned: List[ProcessSpec] = field(default_factory=list)
    alive: Dict[int, ProcessHandle] = field(default_factory=dict)
    open_ports: set = field(default_factory=set)
    ports_after_spawn: set = field(default_factory=set)
    next_pid: int = 1000
    fail_spawn: bool = False

    def spawn(self, spec: ProcessSpec) -> ProcessHandle:
        if self.fail_spawn:
            raise RuntimeError("spawn failed")
        handle = ProcessHandle(pid=self.next_pid, start_time=1.0, exe=spec.argv[0])
        self.next_pid += 1
        self.spawned.append(spec)
        self.alive[handle.pid] = handle
        self.open_ports.update(self.ports_after_spawn)
        return handle

    def stop(self, handle: ProcessHandle) -> None:
        self.alive.pop(handle.pid, None)

    def is_alive(self, handle: ProcessHandle) -> bool:
        return handle.pid in self.alive

    def find(self, name: str) -> List[ProcessHandle]:
        return [handle for handle in self.alive.values() if name in handle.exe]

    def port_listening(self, port: int) -> bool:
        return port in self.open_ports


@dataclass
class FakeKeyboard:
    platform: str = "fake"
    backend: str = "fake"
    bindings: Dict[str, bool] = field(default_factory=dict)
    captured: Optional[str] = None
    available_value: bool = True
    capabilities_value: KeyboardCapabilities = field(default_factory=KeyboardCapabilities)

    def available(self) -> bool:
        return self.available_value

    def capabilities(self) -> KeyboardCapabilities:
        return self.capabilities_value

    def foreground_matches(self, target: str) -> bool:
        return True

    def validate(self, binding: str) -> None:
        if not binding:
            raise ValueError("empty binding")

    def is_down(self, binding: str) -> bool:
        return self.bindings.get(binding, False)

    def capture(self, timeout: float) -> Optional[str]:
        return self.captured


@dataclass
class FakeXPlane:
    info: Optional[XPlaneInfo] = None
    process: Optional[ProcessInfo] = None
    plugin_info: Optional[PluginInfo] = None

    def locate(self) -> Optional[XPlaneInfo]:
        return self.info

    def running(self) -> Optional[ProcessInfo]:
        return self.process

    def plugin(self, aircraft: str) -> Optional[PluginInfo]:
        return self.plugin_info


@dataclass
class FakeInavLocator:
    installs: List[InavInstall] = field(default_factory=list)

    def discover(self) -> List[InavInstall]:
        return list(self.installs)

    def resolve_path(self, path: Path) -> Optional[InavInstall]:
        for install in self.installs:
            if install.path == path:
                return install
        return None


@dataclass
class FakePlatform:
    id: str = "fake"
    process: FakeProcessManager = field(default_factory=FakeProcessManager)
    keyboard: FakeKeyboard = field(default_factory=FakeKeyboard)
    xplane: FakeXPlane = field(default_factory=FakeXPlane)
    inav: FakeInavLocator = field(default_factory=FakeInavLocator)
    paths: FakePaths = field(default_factory=FakePaths)
