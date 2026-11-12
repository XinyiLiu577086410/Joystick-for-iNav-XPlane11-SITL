"""Interactive setup flows (no default bindings, ever)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from ..actions import KEYBOARD_ACTIONS
from ..core.config import BridgeConfig, KeyboardConfig, load_config
from ..platform.base import KeyboardBackend


class SetupError(RuntimeError):
    pass


Capture = Callable[[str], Optional[str]]


@dataclass
class KeyboardSetupService:
    keyboard: KeyboardBackend
    config_path: Path
    platform_id: str
    actions: tuple = KEYBOARD_ACTIONS

    def capture_all(
        self,
        capture: Capture,
        prompt: Callable[[str], None] = lambda action: None,
    ) -> Dict[str, str]:
        keys: Dict[str, str] = {}
        used: Dict[str, str] = {}
        for action in self.actions:
            prompt(action)
            binding = capture(action)
            if not binding:
                raise SetupError(f"no key captured for {action}")
            self.keyboard.validate(binding)
            canonical = binding.strip().lower()
            if canonical in used:
                raise SetupError(f"{binding!r} is already used by {used[canonical]}")
            used[canonical] = action
            keys[action] = binding
        return keys

    def save(self, keys: Dict[str, str]) -> BridgeConfig:
        if not keys:
            raise SetupError("no keyboard bindings to save")
        if self.config_path.is_file():
            config = load_config(self.config_path)
        else:
            config = BridgeConfig(platform=self.platform_id)
        config.platform = self.platform_id
        config.keyboard = KeyboardConfig(
            enabled=True,
            source=config.keyboard.source,
            backend=self.keyboard.backend,
            axis_rate=config.keyboard.axis_rate,
            throttle_rate=config.keyboard.throttle_rate,
            keys=dict(keys),
            foreground_only=config.keyboard.foreground_only,
            window_process=config.keyboard.window_process,
        )
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(asdict(config), indent=2) + "\n",
            encoding="utf-8",
        )
        return config
