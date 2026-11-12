"""Bridge process lifecycle."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..constants import INPUT_MODES
from ..models import ProcessHandle, ProcessSpec
from ..platform.base import Paths, ProcessManager


@dataclass
class BridgeService:
    process: ProcessManager
    paths: Paths
    bridge_script: Path
    python: str = sys.executable

    def command(
        self,
        config_path: Path,
        input_source: Optional[str] = None,
        port: int = 5762,
    ) -> tuple:
        argv = [
            self.python,
            "-u",
            str(self.bridge_script),
            "--config",
            str(config_path),
            "--port",
            str(port),
            "-v",
        ]
        if input_source:
            if input_source not in INPUT_MODES:
                raise ValueError(f"input source must be one of {INPUT_MODES}")
            argv += ["--input", input_source]
        return tuple(argv)

    def start(
        self,
        config_path: Path,
        input_source: Optional[str] = None,
        port: int = 5762,
    ) -> ProcessHandle:
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        return self.process.spawn(
            ProcessSpec(
                argv=self.command(config_path, input_source, port),
                cwd=self.paths.repo_root,
                log_path=self.paths.logs_dir / "bridge.log",
            )
        )

    def stop(self, handle: ProcessHandle) -> None:
        self.process.stop(handle)
