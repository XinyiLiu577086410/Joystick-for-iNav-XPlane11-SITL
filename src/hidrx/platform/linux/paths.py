"""Linux path layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LinuxPaths:
    repo_root: Path
    config_dir: Path
    runtime_dir: Path
    logs_dir: Path
    run_dir: Path

    @classmethod
    def for_repo(cls, repo_root: Path) -> "LinuxPaths":
        return cls(
            repo_root=repo_root,
            config_dir=repo_root / "config",
            runtime_dir=repo_root / "config" / "runtime",
            logs_dir=repo_root / "logs",
            run_dir=repo_root / "run",
        )

    def ensure(self) -> None:
        for path in (self.config_dir, self.runtime_dir, self.logs_dir, self.run_dir):
            path.mkdir(parents=True, exist_ok=True)
