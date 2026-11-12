"""Windows platform composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .inav_locator import WindowsInavLocator
from .keyboard import WindowsKeyboard
from .paths import WindowsPaths
from .processes import Win32ProcessManager
from .xplane import WindowsXPlane


@dataclass
class WindowsPlatform:
    id: str = "windows"
    process: Win32ProcessManager = field(default_factory=Win32ProcessManager)
    keyboard: WindowsKeyboard = field(default_factory=WindowsKeyboard)
    xplane: WindowsXPlane = field(default_factory=WindowsXPlane)
    inav: WindowsInavLocator = field(default_factory=WindowsInavLocator)
    paths: WindowsPaths = field(default_factory=lambda: WindowsPaths.for_repo(Path.cwd()))

    @classmethod
    def for_repo(cls, repo_root: Path) -> "WindowsPlatform":
        process = Win32ProcessManager()
        return cls(
            process=process,
            keyboard=WindowsKeyboard(),
            xplane=WindowsXPlane(process=process),
            inav=WindowsInavLocator(),
            paths=WindowsPaths.for_repo(repo_root),
        )
