"""Composition root: the only place that selects a platform implementation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from .base import Platform

PLATFORM_IDS = {"win32": "windows", "darwin": "macos", "linux": "linux"}


def platform_id_for(sys_platform: str) -> str:
    if sys_platform in PLATFORM_IDS:
        return PLATFORM_IDS[sys_platform]
    if sys_platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"unsupported platform: {sys_platform}")


def create_platform(repo_root: Optional[Path] = None) -> Platform:
    platform_id = platform_id_for(sys.platform)
    if platform_id == "windows":
        from .windows.platform import WindowsPlatform

        return WindowsPlatform.for_repo(repo_root or Path.cwd())
    if platform_id == "macos":
        from .macos.platform import MacOSPlatform

        return MacOSPlatform.for_repo(repo_root or Path.cwd())
    from .linux.platform import LinuxPlatform

    return LinuxPlatform.for_repo(repo_root or Path.cwd())
