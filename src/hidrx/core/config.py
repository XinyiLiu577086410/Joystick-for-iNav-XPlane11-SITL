"""JSON bridge configuration: schema, loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..actions import KEYBOARD_ACTIONS
from .channels import AxisMap, Button3Map, ButtonMap, CombineMap
from ..constants import INPUT_AUTO, INPUT_JOYSTICK, INPUT_KEYBOARD, INPUT_MODES


class ConfigError(ValueError):
    pass


@dataclass
class KeyboardConfig:
    enabled: bool = True
    source: str = INPUT_AUTO
    backend: str = ""
    axis_rate: float = 600.0
    throttle_rate: float = 600.0
    keys: Dict[str, str] = field(default_factory=dict)
    foreground_only: bool = True
    window_process: str = "X-Plane.exe"


@dataclass
class BridgeConfig:
    platform: str = ""
    host: str = "127.0.0.1"
    port: int = 5762
    rate_hz: float = 50.0
    axes: List[AxisMap] = field(default_factory=list)
    buttons: List[ButtonMap] = field(default_factory=list)
    buttons3: List[Button3Map] = field(default_factory=list)
    combine: List[CombineMap] = field(default_factory=list)
    constants: Dict[int, int] = field(default_factory=dict)
    keyboard: KeyboardConfig = field(default_factory=KeyboardConfig)


def normalize_input_source(value: str) -> str:
    source = str(value).strip().lower()
    if source == "hid":
        return INPUT_JOYSTICK
    if source not in INPUT_MODES:
        raise ConfigError(f"input source must be one of {INPUT_MODES}")
    return source


def keyboard_complete(config: KeyboardConfig) -> bool:
    return all(action in config.keys for action in KEYBOARD_ACTIONS)


def has_hid_mapping(config: BridgeConfig) -> bool:
    return bool(config.axes or config.buttons or config.buttons3 or config.combine)


def config_from_dict(data: Dict[str, Any]) -> BridgeConfig:
    if not isinstance(data, dict):
        raise ConfigError("top-level JSON must be an object")

    config = BridgeConfig(
        platform=str(data.get("platform", "")),
        host=str(data.get("host", "127.0.0.1")),
        port=int(data.get("port", 5762)),
        rate_hz=float(data.get("rate_hz", 50.0)),
    )
    config.axes = [AxisMap(**item) for item in data.get("axes", []) or []]
    config.buttons = [ButtonMap(**item) for item in data.get("buttons", []) or []]
    config.buttons3 = [Button3Map(**item) for item in data.get("buttons3", []) or []]
    config.combine = [CombineMap(**item) for item in data.get("combine", []) or []]
    config.constants = {int(k): int(v) for k, v in (data.get("constants") or {}).items()}

    raw_keyboard = data.get("keyboard") or {}
    if not isinstance(raw_keyboard, dict):
        raise ConfigError("keyboard must be an object")
    keys = raw_keyboard.get("keys") or {}
    if not isinstance(keys, dict):
        raise ConfigError("keyboard.keys must be an object")
    config.keyboard = KeyboardConfig(
        enabled=bool(raw_keyboard.get("enabled", True)),
        source=normalize_input_source(raw_keyboard.get("source", INPUT_AUTO)),
        backend=str(raw_keyboard.get("backend", "")),
        axis_rate=float(raw_keyboard.get("axis_rate", 600.0)),
        throttle_rate=float(raw_keyboard.get("throttle_rate", 600.0)),
        keys={str(k): str(v) for k, v in keys.items()},
        foreground_only=bool(raw_keyboard.get("foreground_only", True)),
        window_process=str(raw_keyboard.get("window_process", "X-Plane.exe")),
    )
    return config


def load_config(path: Path) -> BridgeConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    return config_from_dict(data)


def validate_config(config: BridgeConfig, input_source: Optional[str] = None) -> List[str]:
    errors: List[str] = []
    if not config.platform:
        errors.append("platform: missing")
    if not isinstance(config.port, int) or not 1 <= config.port <= 65535:
        errors.append("port: must be 1..65535")
    if config.rate_hz <= 0:
        errors.append("rate_hz: must be > 0")

    channels: Dict[int, str] = {}
    for index, mapping in enumerate(config.axes):
        where = f"axes[{index}]"
        if mapping.channel < 1 or mapping.channel > 16:
            errors.append(f"{where}.channel: must be 1..16")
            continue
        if mapping.channel in channels:
            errors.append(f"{where}.channel: already used by {channels[mapping.channel]}")
        channels[mapping.channel] = where
        if mapping.kind not in {"bipolar", "unipolar", "tri", "binary", "multi"}:
            errors.append(f"{where}.kind: invalid")
    for index, mapping in enumerate(config.buttons):
        where = f"buttons[{index}]"
        if mapping.channel < 1 or mapping.channel > 16:
            errors.append(f"{where}.channel: must be 1..16")
            continue
        if mapping.channel in channels:
            errors.append(f"{where}.channel: already used by {channels[mapping.channel]}")
        channels[mapping.channel] = where
    for channel in config.constants:
        if not 1 <= channel <= 16:
            errors.append(f"constants[{channel}]: channel must be 1..16")

    try:
        source = normalize_input_source(input_source or config.keyboard.source)
    except ConfigError as exc:
        errors.append(str(exc))
        source = INPUT_AUTO

    if source == INPUT_JOYSTICK and not has_hid_mapping(config):
        errors.append("input joystick: no axes/buttons configured; run setup joystick")
    elif source == INPUT_KEYBOARD and not keyboard_complete(config.keyboard):
        errors.append("input keyboard: key bindings incomplete; run setup keyboard")
    elif source == INPUT_AUTO and not has_hid_mapping(config) and not keyboard_complete(config.keyboard):
        errors.append("input auto: no HID mapping and no keyboard bindings; run setup")

    return errors
