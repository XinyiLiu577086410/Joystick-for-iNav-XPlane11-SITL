"""Platform-neutral data models shared by core, services and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Protocol, Sequence, Tuple


@dataclass(frozen=True)
class ProcessHandle:
    """Identity of a managed process, valid on every platform."""

    pid: int
    start_time: float
    exe: str


@dataclass(frozen=True)
class ProcessSpec:
    argv: Tuple[str, ...]
    cwd: Path
    log_path: Path
    detached: bool = True
    env: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class InavInstall:
    version: str
    build: str
    path: Path
    platform: str


@dataclass(frozen=True)
class InavSelection:
    install: InavInstall
    eeprom: Path
    cli_config: Optional[Path]
    source: str


@dataclass(frozen=True)
class EepromMeta:
    version: str
    build: str
    platform: str
    sha256: str = ""


@dataclass(frozen=True)
class KeyboardCapabilities:
    global_keyboard: bool = True
    foreground_gate: bool = True
    combos: bool = True
    reason: str = ""


@dataclass(frozen=True)
class XPlaneInfo:
    path: Path
    version: str


@dataclass(frozen=True)
class PluginInfo:
    installed: bool
    path: Optional[Path] = None
    version: str = ""


@dataclass(frozen=True)
class ProcessInfo:
    handle: ProcessHandle
    name: str


class GamepadDevice(Protocol):
    name: str
    num_axes: int
    num_buttons: int

    def snapshot(self) -> Tuple[Sequence[float], Sequence[int]]: ...

    def close(self) -> None: ...
