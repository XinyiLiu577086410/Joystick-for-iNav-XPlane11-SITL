"""Per-version eeprom backup, restore and reset."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ..models import InavSelection


class EepromError(RuntimeError):
    pass


@dataclass
class EepromService:
    runtime_dir: Path
    backups_dir: Optional[Path] = None

    def __post_init__(self) -> None:
        self.runtime_dir = Path(self.runtime_dir)
        self.backups_dir = Path(self.backups_dir) if self.backups_dir else self.runtime_dir / "backups"

    def _backup_dir(self, version: str) -> Path:
        return self.backups_dir / version

    def backup(self, selection: InavSelection, name: Optional[str] = None) -> Path:
        if not selection.eeprom.is_file():
            raise EepromError(f"no eeprom to back up: {selection.eeprom}")
        label = (name or datetime.now().strftime("%Y%m%d-%H%M%S")).strip()
        if not label or Path(label).name != label:
            raise EepromError(f"invalid backup name: {label!r}")
        destination = self._backup_dir(selection.install.version) / f"{label}.bin"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(selection.eeprom, destination)
        return destination

    def list(self, version: str) -> List[Path]:
        directory = self._backup_dir(version)
        if not directory.is_dir():
            return []
        return sorted(directory.glob("*.bin"))

    def restore(self, selection: InavSelection, name: str) -> Path:
        directory = self._backup_dir(selection.install.version)
        candidates = [
            directory / name,
            directory / f"{name}.bin",
        ]
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            raise EepromError(f"backup not found: {name} for INAV {selection.install.version}")
        selection.eeprom.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, selection.eeprom)
        return source

    def reset(self, selection: InavSelection) -> None:
        for path in (selection.eeprom, selection.eeprom.parent / "meta.json"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
