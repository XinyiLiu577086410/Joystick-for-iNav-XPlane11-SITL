"""Windows INAV SITL discovery and version probing."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from ...models import InavInstall

CREATE_NO_WINDOW = 0x08000000
_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")
_BUILD_RE = re.compile(r"\(([0-9a-fA-F]{6,})\)")


def parse_version_output(text: str) -> tuple[str, str]:
    version = _VERSION_RE.search(text)
    build = _BUILD_RE.search(text)
    return (version.group(1) if version else "unknown", build.group(1) if build else "")


@dataclass
class WindowsInavLocator:
    platform: str = "windows"
    search_roots: List[Path] = field(default_factory=list)
    timeout: float = 5.0

    def _roots(self) -> Iterable[tuple[Path, bool]]:
        env_path = os.environ.get("HIDRX_INAV_PATH", "").strip()
        if env_path:
            yield Path(env_path), True
        for root in self.search_roots:
            yield root, True
        for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            value = os.environ.get(name)
            if value:
                yield Path(value), False
        local = os.environ.get("LOCALAPPDATA")
        if local:
            yield Path(local) / "Programs", False

    def _candidate_exes(self, root: Path, deep: bool = True) -> List[Path]:
        if root.is_file():
            return [root] if root.name.casefold() == "inav_sitl.exe" else []
        if not root.is_dir():
            return []
        result: List[Path] = []
        direct = root / "inav_SITL.exe"
        if direct.is_file():
            result.append(direct)
        if deep:
            for path in root.rglob("inav_SITL.exe"):
                if path not in result:
                    result.append(path)
        else:
            for child in root.iterdir():
                if child.is_dir() and "inav" in child.name.casefold():
                    for path in child.rglob("inav_SITL.exe"):
                        if path not in result:
                            result.append(path)
        return result

    def _probe(self, exe: Path) -> Optional[InavInstall]:
        try:
            with tempfile.TemporaryDirectory() as workdir:
                proc = subprocess.run(
                    [str(exe), "-v"],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=self.timeout,
                    cwd=workdir,
                    creationflags=CREATE_NO_WINDOW,
                )
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        version, build = parse_version_output(text)
        if version == "unknown":
            return None
        return InavInstall(version=version, build=build, path=exe.resolve(), platform=self.platform)

    def discover(self) -> List[InavInstall]:
        found: dict[Path, InavInstall] = {}
        for root, deep in self._roots():
            for exe in self._candidate_exes(root, deep):
                install = self._probe(exe)
                if install is not None:
                    found[install.path] = install
        return sorted(found.values(), key=lambda item: _version_key(item.version))

    def resolve_path(self, path: Path) -> Optional[InavInstall]:
        for exe in self._candidate_exes(path):
            install = self._probe(exe)
            if install is not None:
                return install
        return None


def _version_key(version: str) -> tuple:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)
