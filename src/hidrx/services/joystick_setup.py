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
            (
                "roll",
                1,
                "bipolar",
                "先把横滚摇杆回中，然后只把横滚摇杆向左或向右打到最大，保持约 1 秒再松开",
            ),
            (
                "pitch",
                2,
                "bipolar",
                "先松开所有摇杆，然后只把俯仰摇杆向上或向下打到最大，保持约 1 秒再松开",
            ),
            (
                "yaw",
                4,
                "bipolar",
                "先松开所有摇杆，然后只把偏航摇杆向左或向右打到最大，保持约 1 秒再松开",
            ),
            (
                "throttle",
                3,
                "unipolar",
                "先把油门拉到最低，再缓慢推到最高，保持约 1 秒再松开",
            ),
        )
        axes: List[AxisMap] = []
        used_axes: dict[int, str] = {}
        for label, channel, kind, instruction in specs:
            for attempt in range(3):
                suffix = "" if attempt == 0 else "（上一次检测到重复轴，请重新做一次）"
                prompt(f"CH{channel} {label}：{instruction}{suffix}")
                axis, delta = detect_axis(device, self.timeout)
                if axis in used_axes:
                    prompt(
                        f"检测到 axis {axis} 已经是 {used_axes[axis]} 的轴；"
                        f"请松开所有摇杆，只移动 {label} 摇杆，再试一次"
                    )
                    continue
                used_axes[axis] = label
                axes.append(
                    AxisMap(
                        axis=axis,
                        channel=channel,
                        kind=kind,
                        reverse=delta < 0,
                        trim=PWM_MIN if kind == "unipolar" else 1500,
                    )
                )
                time.sleep(0.3)
                break
            else:
                raise SetupError(
                    f"{label}: 连续 3 次检测到已被其他通道占用的轴（"
                    + ", ".join(f"axis {number}={name}" for number, name in used_axes.items())
                    + "）；请确认只移动对应的摇杆"
                )

        for attempt in range(3):
            suffix = "" if attempt == 0 else "（上一次检测到重复轴，请重新做一次）"
            prompt(
                "CH8 mode：先把模式旋钮依次经过 6 个档位，然后停在任意档并保持约 1 秒"
                + suffix
            )
            mode_axis, _ = detect_axis(device, self.timeout)
            if mode_axis in used_axes:
                prompt(
                    f"检测到 axis {mode_axis} 已经是 {used_axes[mode_axis]} 的轴；"
                    "模式档位需要一个独立的旋钮轴，请换一个旋钮再试"
                )
                continue
            used_axes[mode_axis] = "mode"
            axes.append(
                AxisMap(
                    axis=mode_axis,
                    channel=8,
                    kind="multi",
                    levels=6,
                    values=list(MODE_VALUES),
                )
            )
            time.sleep(0.3)
            break
        else:
            raise SetupError("mode: 连续 3 次检测到已占用轴；模式档位必须使用独立旋钮")

        prompt("CH7 arm：按一下平时用于解锁/上锁的按钮")
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
