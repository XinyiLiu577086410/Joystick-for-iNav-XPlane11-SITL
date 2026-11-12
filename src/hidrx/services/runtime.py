"""Persist component process handles between CLI invocations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models import ProcessHandle


@dataclass
class RuntimeStore:
    run_dir: Path

    def path(self, component: str) -> Path:
        return self.run_dir / f"{component}.json"

    def save(self, component: str, handle: ProcessHandle) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path(component).write_text(
            json.dumps(
                {"pid": handle.pid, "start_time": handle.start_time, "exe": handle.exe},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def load(self, component: str) -> Optional[ProcessHandle]:
        path = self.path(component)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ProcessHandle(
                pid=int(data["pid"]),
                start_time=float(data.get("start_time", 0.0)),
                exe=str(data.get("exe", "")),
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def remove(self, component: str) -> None:
        try:
            self.path(component).unlink()
        except OSError:
            pass
