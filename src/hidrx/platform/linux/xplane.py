"""Linux X-Plane and HITL plugin discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ...models import PluginInfo, ProcessInfo, XPlaneInfo
from ..posix.processes import PosixProcessManager


@dataclass
class LinuxXPlane:
    platform: str = "linux"
    search_roots: List[Path] = field(default_factory=list)
    process: PosixProcessManager = field(default_factory=PosixProcessManager)

    def _roots(self) -> List[Path]:
        roots: List[Path] = []
        env_path = os.environ.get("XPLANE_PATH", "").strip()
        if env_path:
            roots.append(Path(env_path))
        roots.extend(self.search_roots)
        home = Path.home()
        roots.extend(
            [
                home / ".steam" / "steam" / "steamapps" / "common" / "X-Plane 11",
                home / ".local" / "share" / "Steam" / "steamapps" / "common" / "X-Plane 11",
                home / ".steam" / "steam" / "steamapps" / "common" / "X-Plane 12",
                Path("/opt/X-Plane 11"),
                Path("/opt/X-Plane 12"),
            ]
        )
        return roots

    def locate(self) -> Optional[XPlaneInfo]:
        for root in self._roots():
            if (root / "X-Plane-x86_64").is_file() or (root / "X-Plane").is_file():
                return XPlaneInfo(path=root.resolve(), version="")
        return None

    def running(self) -> Optional[ProcessInfo]:
        handles = self.process.find("X-Plane")
        if not handles:
            return None
        return ProcessInfo(handle=handles[0], name="X-Plane")

    def plugin(self, aircraft: str) -> Optional[PluginInfo]:
        info = self.locate()
        if info is None:
            return None
        candidates = [
            info.path / "Aircraft" / aircraft / "plugins" / "INAV-X-Plane-HITL" / "64" / "lin.xpl",
            info.path / "Aircraft" / aircraft / "plugins" / "INAV-X-Plane-HITL" / "lin.xpl",
            info.path / "Resources" / "plugins" / "INAV-X-Plane-HITL" / "64" / "lin.xpl",
        ]
        for path in candidates:
            if path.is_file():
                return PluginInfo(installed=True, path=path, version="")
        return PluginInfo(installed=False)
