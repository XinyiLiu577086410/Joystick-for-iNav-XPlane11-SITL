"""Guided gamepad setup: detect axes/buttons, never invent defaults."""

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
    threshold: float = 0.7,
    hold_seconds: float = 1.0,
    interval: float = 0.02,
    exclude_axes: set[int] | None = None,
) -> tuple[int, float]:
    baseline, _ = device.snapshot()
    deadline = time.monotonic() + timeout
    candidate_axis: int | None = None
    candidate_sign = 0
    hold_start: float | None = None
    while time.monotonic() < deadline:
        now = time.monotonic()
        axes, _ = device.snapshot()
        if len(axes) == len(baseline):
            deltas = [axes[i] - baseline[i] for i in range(len(axes))]
            candidates = [
                index
                for index in range(len(deltas))
                if not exclude_axes or index not in exclude_axes
            ]
            if candidates:
                axis = max(candidates, key=lambda index: abs(deltas[index]))
                delta = deltas[axis]
                sign = 1 if delta > 0 else -1
                if abs(delta) >= threshold:
                    if hold_seconds <= 0:
                        return axis, delta
                    if axis != candidate_axis or sign != candidate_sign:
                        candidate_axis = axis
                        candidate_sign = sign
                        hold_start = now
                    elif hold_start is not None and now - hold_start >= hold_seconds:
                        return axis, delta
                else:
                    candidate_axis = None
                    hold_start = None
        time.sleep(interval)
    raise SetupError("timed out waiting for a stick to reach its maximum and hold")


def detect_button(
    device: GamepadDevice,
    timeout: float = 15.0,
    interval: float = 0.02,
) -> int:
    """Wait for one button to change and then return to its original state."""
    _, baseline = device.snapshot()
    target: int | None = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, buttons = device.snapshot()
        if target is None:
            changed = [
                index
                for index, pressed in enumerate(buttons)
                if index < len(baseline) and bool(pressed) != bool(baseline[index])
            ]
            if len(changed) == 1:
                target = changed[0]
            elif len(changed) > 1:
                pass  # ignore ambiguous multi-button changes; wait for one switch
        else:
            if target < len(buttons) and bool(buttons[target]) == bool(baseline[target]):
                return target
        time.sleep(interval)
    raise SetupError("timed out waiting for a button to change and return")


def detect_switch(
    device: GamepadDevice,
    label: str,
    prompt: Callable[[str], None],
    confirm: Callable[[str], None],
    timeout: float = 15.0,
    interval: float = 0.02,
    low_label: str = "LOW/关",
    high_label: str = "HIGH/开",
) -> tuple[int, bool]:
    prompt(f"{label}：把开关拨到「{low_label}」位置")
    confirm(f"确认「{low_label}」状态后开始检测「{high_label}」")
    _, low = device.snapshot()
    prompt(f"{label}：现在把开关拨到「{high_label}」位置")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, high = device.snapshot()
        changed = [
            index
            for index, pressed in enumerate(high)
            if index < len(low) and bool(pressed) != bool(low[index])
        ]
        if len(changed) == 1:
            button = changed[0]
            prompt(f"已检测到 {label}：button {button}，「{high_label}」状态={bool(high[button])}")
            confirm("确认这一项，再采集下一项")
            return button, not bool(high[button])
        if len(changed) > 1:
            prompt(f"{label}: 多个按钮同时变化 {changed}；只拨动一个开关，重试")
        time.sleep(interval)
    raise SetupError(f"{label}: 没有检测到开关变化")


@dataclass
class GamepadSetupService:
    config_path: Path
    platform_id: str
    keyboard_backend: str
    timeout: float = 10.0
    hold_seconds: float = 1.0
    mode_hold_seconds: float = 3.0

    def _sample_direction(
        self,
        device: GamepadDevice,
        prompt: Callable[[str], None],
        confirm: Callable[[str], None],
        control: str,
        direction: str,
        throttle: bool = False,
    ) -> tuple[int, float]:
        for attempt in range(3):
            if throttle:
                text = f"{control}：把油门拉到「{direction}」位置，保持约 1 秒再松开"
            else:
                text = f"{control}：把摇杆向「{direction}」打到最大，保持约 1 秒再松开"
            if attempt:
                text += "（上一次没有检测到，请重试）"
            prompt(text)
            try:
                axis, delta = detect_axis(
                    device,
                    self.timeout,
                    hold_seconds=self.hold_seconds,
                )
            except SetupError:
                if attempt == 2:
                    raise
                continue
            sign = "正" if delta > 0 else "负"
            prompt(f"已检测到 {control}：axis {axis}，{sign}方向（变化 {delta:+.2f}）")
            confirm("确认这一项，再采集下一项")
            time.sleep(0.2)
            return axis, delta
        raise SetupError(f"{control}: 没有检测到有效的摇杆移动")

    def _capture_pair(
        self,
        device: GamepadDevice,
        prompt: Callable[[str], None],
        confirm: Callable[[str], None],
        label: str,
        channel: int,
        kind: str,
        first_direction: str,
        second_direction: str,
        first_is_low: bool,
        used_axes: dict[int, str],
    ) -> AxisMap:
        for attempt in range(3):
            suffix = "" if attempt == 0 else "（上一次检测失败，请重新做这两个方向）"
            if suffix:
                prompt(suffix)
            axis1, delta1 = self._sample_direction(
                device, prompt, confirm, label, first_direction, throttle=kind == "unipolar"
            )
            axis2, delta2 = self._sample_direction(
                device, prompt, confirm, label, second_direction, throttle=kind == "unipolar"
            )
            if axis1 != axis2:
                prompt(f"{label}: 两个方向检测到了不同轴（axis {axis1} / axis {axis2}），重试")
                continue
            if delta1 * delta2 >= 0:
                prompt(f"{label}: 两个方向没有形成正/负反向，重试")
                continue
            if axis1 in used_axes:
                prompt(
                    f"{label}: axis {axis1} 已经被 {used_axes[axis1]} 使用；"
                    "请松开所有摇杆，只动这一项，重试"
                )
                continue
            used_axes[axis1] = label
            reverse = delta1 > 0 if first_is_low else delta1 < 0
            return AxisMap(
                axis=axis1,
                channel=channel,
                kind=kind,
                reverse=reverse,
                trim=PWM_MIN if kind == "unipolar" else 1500,
            )
        raise SetupError(
            f"{label}: 连续 3 次没有采集到两个方向一致的轴；"
            "请确认只移动对应摇杆，并且两个方向都打到最大"
        )

    def capture(
        self,
        device: GamepadDevice,
        prompt: Callable[[str], None] = lambda text: None,
        confirm: Callable[[str], None] = lambda text: None,
    ) -> BridgeConfig:
        prompt("开始前：把所有摇杆回中")
        confirm("确认所有摇杆已回中")

        specs = (
            ("横滚 roll", 1, "bipolar", "左", "右", True),
            ("俯仰 pitch", 2, "bipolar", "上仰方向", "下俯方向", True),
            ("偏航 yaw", 4, "bipolar", "左", "右", True),
            ("油门 throttle", 3, "unipolar", "最低", "最高", True),
        )
        axes: List[AxisMap] = []
        used_axes: dict[int, str] = {}
        for label, channel, kind, first, second, first_is_low in specs:
            axes.append(
                self._capture_pair(
                    device,
                    prompt,
                    confirm,
                    label,
                    channel,
                    kind,
                    first,
                    second,
                    first_is_low,
                    used_axes,
                )
            )

        for attempt in range(3):
            suffix = "" if attempt == 0 else "（上一次没有检测到，请重新做一次）"
            prompt("模式 mode：把模式旋钮转到最低档（第 1 档）" + suffix)
            confirm("确认模式旋钮在最低档")
            prompt("模式 mode：现在把旋钮转到最高档（第 6 档），保持约 3 秒")
            try:
                mode_axis, mode_delta = detect_axis(
                    device,
                    self.timeout,
                    threshold=0.8,
                    hold_seconds=max(self.mode_hold_seconds, self.hold_seconds),
                    exclude_axes=set(used_axes),
                )
            except SetupError:
                if attempt == 2:
                    raise
                continue
            prompt(f"已检测到 模式 mode：axis {mode_axis}，变化 {mode_delta:+.2f}")
            confirm("确认这一项，再采集下一项")
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
                    reverse=mode_delta < 0,
                )
            )
            time.sleep(0.2)
            break
        else:
            raise SetupError("mode: 连续 3 次没有检测到最低档到最高档的移动")

        wp_button, wp_inverted = detect_switch(
            device,
            "CH6 NAV WP",
            prompt,
            confirm,
            timeout=max(self.timeout, 15.0),
        )
        buttons = [
            ButtonMap(
                button=wp_button,
                channel=6,
                low=2000 if wp_inverted else 1000,
                high=1000 if wp_inverted else 2000,
                toggle=False,
            )
        ]

        for attempt in range(3):
            arm_button, arm_inverted = detect_switch(
                device,
                "CH7 arm",
                prompt,
                confirm,
                timeout=max(self.timeout, 15.0),
                low_label="上锁/未解锁",
                high_label="解锁",
            )
            if arm_button == wp_button:
                prompt(
                    f"CH6 NAV WP 和 arm 都检测到 button {arm_button}；"
                    "请换一个按钮/开关给 arm，再试一次"
                )
                continue
            buttons.append(
                ButtonMap(
                    button=arm_button,
                    channel=7,
                    low=2000 if arm_inverted else 1000,
                    high=1000 if arm_inverted else 2000,
                    toggle=False,
                )
            )
            break
        else:
            raise SetupError("arm: 连续 3 次与 CH6 NAV WP 使用了同一个按钮")

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
