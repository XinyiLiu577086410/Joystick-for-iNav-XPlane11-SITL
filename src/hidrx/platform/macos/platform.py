"""macOS platform composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .inav_locator import MacOSInavLocator
from .keyboard import MacOSKeyboard
from .paths import MacOSPaths
from .xplane import MacOSXPlane
from ..posix.processes import PosixProcessManager


@dataclass
class MacOSPlatform:
    id: str = "macos"
    process: PosixProcessManager = field(default_factory=PosixProcessManager)
    keyboard: MacOSKeyboard = field(default_factory=MacOSKeyboard)
    xplane: MacOSXPlane = field(default_factory=MacOSXPlane)
    inav: MacOSInavLocator = field(default_factory=MacOSInavLocator)
    paths: MacOSPaths = field(default_factory=lambda: MacOSPaths.for_repo(Path.cwd()))

    @classmethod
    def for_repo(cls, repo_root: Path) -> "MacOSPlatform":
        process = PosixProcessManager()
        return cls(
            process=process,
            keyboard=MacOSKeyboard(),
            xplane=MacOSXPlane(process=process),
            inav=MacOSInavLocator(),
            paths=MacOSPaths.for_repo(repo_root),
        )
