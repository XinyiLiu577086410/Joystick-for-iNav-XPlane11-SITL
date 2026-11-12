"""Guided joystick setup: detect axes/buttons, never invent defaults."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List

from ..core.channels import AxisMap, ButtonMap
from ..core.config import BridgeConfig, KeyboardConfig, load_config
from ..constants import MODE_VALUES, PWM_MIN
from ..platform.gamepad import GamepadDevice
from .setup import SetupError


def detect_axis(
    device: GamepadDevice,
    timeout: float = 10.0,
    threshold: float = 0.35,
    interval: float = 0.02,
) -> tuple[int, float]:
    baseline, _ = device.snapshot()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        axes, _ = device.snapshot()
        if len(axes) == len(baseline):
            deltas = [abs(axes[i] - baseline[i]) for i in range(len(axes))]
            if deltas:
                axis = max(range(len(deltas)), key=deltas.__getitem__)
                if deltas[axis] > threshold:
                    return axis, axes[axis] - baseline[axis]
        time.sleep(interval)
    raise SetupError("timed out waiting for axis movement")


def detect_button(
    device: GamepadDevice,
    timeout: float = 10.0,
    interval: float = 0.02,
) -> int:
    _, baseline = device.snapshot()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, buttons = device.snapshot()
        for index, pressed in enumerate(buttons):
            if pressed and (index >= len(baseline) or not baseline[index]):
                return index
        time.sleep(interval)
    raise SetupError("timed out waiting for button press")


@dataclass
class JoystickSetupService:
    config_path: Path
    platform_id: str
    keyboard_backend: str
    timeout: float = 10.0

    def capture(
        self,
        device: GamepadDevice,
        prompt: Callable[[str], None] = lambda text: None,
    ) -> BridgeConfig:
        specs = (
            ("roll", 1, "bipolar"),
            ("pitch", 2, "bipolar"),
            ("yaw", 4, "bipolar"),
            ("throttle", 3, "unipolar"),
        )
        axes: List[AxisMap] = []
        used_axes: set = set()
        for label, channel, kind in specs:
            prompt(f"Move the {label} stick to its maximum and hold it")
            axis, delta = detect_axis(device, self.timeout)
            if axis in used_axes:
                raise SetupError(f"axis {axis} was already assigned")
            used_axes.add(axis)
            axes.append(
                AxisMap(
                    axis=axis,
                    channel=channel,
                    kind=kind,
                    reverse=delta < 0,
                    trim=PWM_MIN if kind == "unipolar" else 1500,
                )
            )
            time.sleep(0.2)

        prompt("Move the mode knob through all six positions")
        mode_axis, _ = detect_axis(device, self.timeout)
        if mode_axis in used_axes:
            raise SetupError(f"mode axis {mode_axis} was already assigned")
        axes.append(
            AxisMap(
                axis=mode_axis,
                channel=8,
                kind="multi",
                levels=6,
                values=list(MODE_VALUES),
            )
        )

        prompt("Press the arm button")
        arm_button = detect_button(device, self.timeout)
        buttons = [ButtonMap(button=arm_button, channel=7, toggle=True)]

        return BridgeConfig(
            platform=self.platform_id,
            axes=axes,
            buttons=buttons,
            keyboard=KeyboardConfig(backend=self.keyboard_backend, keys={}),
        )

    def save(self, config: BridgeConfig) -> BridgeConfig:
        if self.config_path.is_file():
            existing = load_config(self.config_path)
            config.host = existing.host
            config.port = existing.port
            config.rate_hz = existing.rate_hz
            config.keyboard = existing.keyboard
            config.keyboard.backend = self.keyboard_backend
        config.platform = self.platform_id
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(asdict(config), indent=2) + "\n",
            encoding="utf-8",
        )
        return config
