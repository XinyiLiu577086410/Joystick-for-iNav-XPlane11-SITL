"""Linux platform composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .inav_locator import LinuxInavLocator
from .keyboard import LinuxKeyboard
from .paths import LinuxPaths
from .xplane import LinuxXPlane
from ..posix.processes import PosixProcessManager


@dataclass
class LinuxPlatform:
    id: str = "linux"
    process: PosixProcessManager = field(default_factory=PosixProcessManager)
    keyboard: LinuxKeyboard = field(default_factory=LinuxKeyboard)
    xplane: LinuxXPlane = field(default_factory=LinuxXPlane)
    inav: LinuxInavLocator = field(default_factory=LinuxInavLocator)
    paths: LinuxPaths = field(default_factory=lambda: LinuxPaths.for_repo(Path.cwd()))

    @classmethod
    def for_repo(cls, repo_root: Path) -> "LinuxPlatform":
        process = PosixProcessManager()
        return cls(
            process=process,
            keyboard=LinuxKeyboard(),
            xplane=LinuxXPlane(process=process),
            inav=LinuxInavLocator(),
            paths=LinuxPaths.for_repo(repo_root),
        )
