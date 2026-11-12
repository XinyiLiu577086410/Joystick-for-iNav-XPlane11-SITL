"""Doctor checks for platform, INAV, config and X-Plane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..core.config import ConfigError
from ..platform.base import Platform
from .config import ConfigService
from .inav import InavError, InavService
from .runtime import RuntimeStore


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    warning: bool = False


@dataclass
class DoctorService:
    platform: Platform
    inav: InavService
    config: ConfigService
    store: RuntimeStore
    aircraft: str = "NK_FPVSurfwing"

    def collect(self) -> List[Check]:
        checks: List[Check] = []
        checks.append(Check("platform", True, self.platform.id))

        try:
            available = self.platform.keyboard.available()
            caps = self.platform.keyboard.capabilities()
            detail = f"backend={self.platform.keyboard.backend} available={available} global={caps.global_keyboard}"
            if caps.reason:
                detail += f" ({caps.reason})"
            checks.append(Check("keyboard", available, detail, warning=not caps.foreground_gate))
        except OSError as exc:
            checks.append(Check("keyboard", False, str(exc)))

        try:
            xplane = self.platform.xplane.locate()
            running = self.platform.xplane.running()
            checks.append(
                Check(
                    "xplane",
                    xplane is not None,
                    f"{xplane.path if xplane else 'not found'} running={running is not None}",
                    warning=xplane is not None and running is None,
                )
            )
            if xplane is not None:
                plugin = self.platform.xplane.plugin(self.aircraft)
                installed = bool(plugin and plugin.installed)
                checks.append(
                    Check(
                        "hitl plugin",
                        installed,
                        str(plugin.path) if plugin and plugin.path else "not installed",
                        warning=not installed,
                    )
                )
        except OSError as exc:
            checks.append(Check("xplane", False, str(exc)))

        try:
            installs = self.inav.list()
            checks.append(
                Check(
                    "inav installs",
                    bool(installs),
                    ", ".join(item.version for item in installs) or "none",
                )
            )
            selection = self.inav.resolve()
            checks.append(
                Check(
                    "inav selection",
                    True,
                    f"{selection.install.version} ({selection.source}) {selection.install.path}",
                )
            )
            try:
                self.inav.ensure_eeprom(selection)
                checks.append(Check("eeprom", True, str(selection.eeprom)))
            except InavError as exc:
                checks.append(Check("eeprom", False, str(exc)))
        except InavError as exc:
            checks.append(Check("inav installs", False, str(exc)))

        try:
            config = self.config.load()
            checks.append(Check("config", True, str(self.config.config_path)))
            try:
                self.config.plan(config)
                checks.append(Check("startup guard", True, "platform/backend/input mapping"))
            except Exception as exc:
                checks.append(Check("startup guard", False, str(exc)))
        except ConfigError as exc:
            checks.append(Check("config", False, str(exc)))

        for name in ("sitl", "bridge"):
            handle = self.store.load(name)
            if handle is None:
                continue
            try:
                alive = self.platform.process.is_alive(handle)
            except OSError:
                alive = False
            checks.append(Check(name, True, f"running pid={handle.pid}" if alive else "stale record", warning=True))
        return checks

    def failed(self) -> List[Check]:
        return [check for check in self.collect() if not check.ok and not check.warning]
