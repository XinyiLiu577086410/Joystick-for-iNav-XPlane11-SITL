"""Interactive setup flows (no default bindings, ever)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from ..actions import KEYBOARD_ACTION_LABELS, KEYBOARD_ACTIONS
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
        report: Callable[[str], None] = lambda text: None,
    ) -> Dict[str, str]:
        keys: Dict[str, str] = {}
        used: Dict[str, str] = {}
        for action in self.actions:
            label = KEYBOARD_ACTION_LABELS.get(action, action)
            for attempt in range(3):
                prompt(action)
                binding = capture(action)
                if not binding:
                    report(f"「{label}」没有捕获到按键，重试")
                    continue
                try:
                    self.keyboard.validate(binding)
                except ValueError as exc:
                    report(f"「{label}」的按键 {binding!r} 无效：{exc}，重试")
                    continue
                canonical = binding.strip().lower()
                if canonical in used:
                    previous = KEYBOARD_ACTION_LABELS.get(used[canonical], used[canonical])
                    report(
                        f"「{label}」的按键 {binding!r} 已被「{previous}」使用；"
                        "请换一个按键，重试"
                    )
                    continue
                used[canonical] = action
                keys[action] = binding
                break
            else:
                raise SetupError(f"「{label}」连续 3 次没有采集到唯一有效按键")
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
