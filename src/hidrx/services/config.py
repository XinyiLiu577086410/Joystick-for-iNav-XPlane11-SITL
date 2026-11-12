"""Bridge configuration service: load once, then gate startup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.config import BridgeConfig, load_config
from ..core.startup import StartupPlan, require_ready


@dataclass
class ConfigService:
    config_path: Path
    platform_id: str
    keyboard_backend: str

    def load(self) -> BridgeConfig:
        return load_config(self.config_path)

    def plan(self, config: BridgeConfig, input_source: Optional[str] = None) -> StartupPlan:
        return require_ready(
            config,
            platform_id=self.platform_id,
            backend_id=self.keyboard_backend,
            input_source=input_source,
        )
