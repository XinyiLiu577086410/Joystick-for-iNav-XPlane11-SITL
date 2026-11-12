"""Aggregate status for CLI output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from ..core.config import ConfigError
from ..models import InavSelection
from ..platform.base import Platform
from .config import ConfigService
from .inav import InavError, InavService
from .runtime import RuntimeStore


@dataclass(frozen=True)
class ComponentStatus:
    name: str
    running: bool
    pid: Optional[int] = None
    exe: Optional[str] = None


@dataclass
class StatusReport:
    platform: str
    components: Dict[str, ComponentStatus] = field(default_factory=dict)
    inav: Optional[dict] = None
    inav_error: str = ""
    config: dict = field(default_factory=dict)
    ports: Dict[int, bool] = field(default_factory=dict)
    xplane: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "platform": self.platform,
            "components": {
                name: {
                    "running": item.running,
                    "pid": item.pid,
                    "exe": item.exe,
                }
                for name, item in self.components.items()
            },
            "inav": self.inav,
            "inav_error": self.inav_error,
            "config": self.config,
            "ports": {str(port): open_ for port, open_ in self.ports.items()},
            "xplane": self.xplane,
        }


@dataclass
class StatusService:
    platform: Platform
    inav: InavService
    config: ConfigService
    store: RuntimeStore
    base_port: int = 5760

    def _component(self, name: str) -> ComponentStatus:
        handle = self.store.load(name)
        if handle is None:
            return ComponentStatus(name=name, running=False)
        running = False
        try:
            running = self.platform.process.is_alive(handle)
        except OSError:
            running = False
        if not running:
            self.store.remove(name)
            return ComponentStatus(name=name, running=False)
        return ComponentStatus(name=name, running=True, pid=handle.pid, exe=handle.exe)

    def collect(self) -> StatusReport:
        report = StatusReport(platform=self.platform.id)
        for name in ("sitl", "bridge"):
            report.components[name] = self._component(name)

        try:
            selection: Optional[InavSelection] = self.inav.resolve()
        except InavError as exc:
            selection = None
            report.inav_error = str(exc)
        if selection is not None:
            report.inav = {
                "version": selection.install.version,
                "build": selection.install.build,
                "path": str(selection.install.path),
                "eeprom": str(selection.eeprom),
                "source": selection.source,
            }

        try:
            config = self.config.load()
            report.config = {"path": str(self.config.config_path), "loaded": True}
            try:
                self.config.plan(config)
            except Exception as exc:
                report.config["error"] = str(exc)
        except ConfigError as exc:
            report.config = {"path": str(self.config.config_path), "loaded": False, "error": str(exc)}

        for offset in range(4):
            port = self.base_port + offset
            try:
                report.ports[port] = self.platform.process.port_listening(port)
            except OSError:
                report.ports[port] = False

        try:
            info = self.platform.xplane.locate()
            running = self.platform.xplane.running()
            report.xplane = {
                "path": str(info.path) if info else None,
                "version": info.version if info else "",
                "running": running is not None,
            }
        except OSError:
            report.xplane = {"path": None, "version": "", "running": False}
        return report
