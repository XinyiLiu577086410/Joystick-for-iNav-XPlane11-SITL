"""Windows X-Plane installation, process and HITL plugin discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ...models import PluginInfo, ProcessInfo, XPlaneInfo
from .processes import Win32ProcessManager


@dataclass
class WindowsXPlane:
    platform: str = "windows"
    search_roots: List[Path] = field(default_factory=list)
    process: Win32ProcessManager = field(default_factory=Win32ProcessManager)

    def _roots(self) -> List[Path]:
        roots: List[Path] = []
        env_path = os.environ.get("XPLANE_PATH", "").strip()
        if env_path:
            roots.append(Path(env_path))
        roots.extend(self.search_roots)
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                for name in ("X-Plane 11", "X-Plane 12"):
                    roots.append(Path(base) / name)
                steam = Path(base) / "Steam" / "steamapps" / "common"
                roots.extend([steam / "X-Plane 11", steam / "X-Plane 12"])
        home = Path.home()
        roots.extend(
            [
                home / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "X-Plane 11",
                home / ".steam" / "steam" / "steamapps" / "common" / "X-Plane 11",
            ]
        )
        return roots

    def locate(self) -> Optional[XPlaneInfo]:
        for root in self._roots():
            exe = root / "X-Plane.exe"
            if exe.is_file():
                return XPlaneInfo(path=root.resolve(), version="")
        return None

    def running(self) -> Optional[ProcessInfo]:
        handles = self.process.find("X-Plane.exe")
        if not handles:
            return None
        handle = handles[0]
        return ProcessInfo(handle=handle, name="X-Plane.exe")

    def plugin(self, aircraft: str) -> Optional[PluginInfo]:
        info = self.locate()
        if info is None:
            return None
        candidates = [
            info.path / "Aircraft" / aircraft / "plugins" / "INAV-X-Plane-HITL" / "64" / "win.xpl",
            info.path / "Aircraft" / aircraft / "plugins" / "INAV-X-Plane-HITL" / "win.xpl",
            info.path / "Resources" / "plugins" / "INAV-X-Plane-HITL" / "64" / "win.xpl",
            info.path / "Resources" / "plugins" / "INAV-X-Plane-HITL" / "win.xpl",
        ]
        for path in candidates:
            if path.is_file():
                return PluginInfo(installed=True, path=path, version="")
        return PluginInfo(installed=False)
