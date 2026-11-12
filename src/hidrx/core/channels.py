"""Channel mapping: sticks, buttons, switches and flight modes."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Sequence

from ..constants import CHANNEL_COUNT, PWM_MAX, PWM_MID, PWM_MIN

if TYPE_CHECKING:
    from .config import BridgeConfig


@dataclass
class AxisMap:
    axis: int
    channel: int
    kind: str = "bipolar"  # bipolar / unipolar / tri / binary / multi
    reverse: bool = False
    trim: int = PWM_MID
    deadband: float = 0.06
    expo: float = 0.0
    threshold: float = 0.0
    levels: int = 6
    values: List[int] = field(default_factory=list)


@dataclass
class ButtonMap:
    button: int
    channel: int
    low: int = PWM_MIN
    high: int = PWM_MAX
    toggle: bool = True


@dataclass
class Button3Map:
    channel: int
    up: int = -1
    down: int = -1
    low: int = PWM_MIN
    mid: int = PWM_MID
    high: int = PWM_MAX


@dataclass
class CombineMap:
    channel: int
    a: int
    b: int
    a_levels: int = 3
    b_levels: int = 2
    values: List[int] = field(default_factory=lambda: [1000, 1200, 1400, 1600, 1800, 2000])


def clamp_pwm(value: float) -> int:
    return int(max(PWM_MIN, min(PWM_MAX, round(value))))


def apply_deadband(value: float, deadband: float) -> float:
    if abs(value) <= deadband:
        return 0.0
    return math.copysign((abs(value) - deadband) / (1.0 - deadband), value)


def apply_expo(value: float, expo: float) -> float:
    return (1.0 - expo) * value + expo * value * value * value


def axis_to_pwm(raw: float, mapping: AxisMap) -> int:
    value = -raw if mapping.reverse else raw
    value = max(-1.0, min(1.0, value))
    if mapping.kind == "unipolar":
        value = max(0.0, value)
        return clamp_pwm(mapping.trim + value * (PWM_MAX - mapping.trim))
    if mapping.kind == "tri":
        if value < mapping.threshold - 0.33:
            return PWM_MIN
        if value < mapping.threshold + 0.33:
            return PWM_MID
        return PWM_MAX
    if mapping.kind == "binary":
        return PWM_MAX if value >= mapping.threshold else PWM_MIN
    if mapping.kind == "multi":
        count = max(2, mapping.levels)
        index = int(round((value + 1.0) * (count - 1) / 2.0))
        index = max(0, min(count - 1, index))
        if mapping.values and len(mapping.values) >= count:
            return clamp_pwm(mapping.values[index])
        return clamp_pwm(PWM_MIN + index * (PWM_MAX - PWM_MIN) / (count - 1))
    value = apply_deadband(value, mapping.deadband)
    value = apply_expo(value, mapping.expo)
    return clamp_pwm(mapping.trim + value * 500.0)


def pwm_to_level(value: int, levels: int) -> int:
    if levels <= 1:
        return 0
    if levels == 2:
        return 1 if value >= PWM_MID else 0
    if levels == 3:
        if value < 1250:
            return 0
        if value < 1750:
            return 1
        return 2
    span = (PWM_MAX - PWM_MIN) / max(1, levels - 1)
    return max(0, min(levels - 1, int(round((value - PWM_MIN) / span))))


def build_channels(
    config: "BridgeConfig",
    axes: Sequence[float],
    buttons: Sequence[int],
    toggles: Dict[int, bool],
    previous: Dict[int, bool],
) -> List[int]:
    channels = [PWM_MID] * CHANNEL_COUNT
    channels[2] = PWM_MIN

    for mapping in config.axes:
        if mapping.axis < len(axes):
            channels[mapping.channel - 1] = axis_to_pwm(axes[mapping.axis], mapping)

    for mapping in config.buttons:
        if mapping.button >= len(buttons):
            continue
        pressed = bool(buttons[mapping.button])
        was_pressed = previous.get(mapping.button, False)
        if mapping.toggle:
            if pressed and not was_pressed:
                toggles[mapping.button] = not toggles.get(mapping.button, False)
            channels[mapping.channel - 1] = (
                mapping.high if toggles.get(mapping.button, False) else mapping.low
            )
        else:
            channels[mapping.channel - 1] = mapping.high if pressed else mapping.low
        previous[mapping.button] = pressed

    for mapping in config.buttons3:
        up = 0 <= mapping.up < len(buttons) and bool(buttons[mapping.up])
        down = 0 <= mapping.down < len(buttons) and bool(buttons[mapping.down])
        channels[mapping.channel - 1] = (
            mapping.high if up else (mapping.low if down else mapping.mid)
        )

    for mapping in config.combine:
        a_level = pwm_to_level(channels[mapping.a - 1], mapping.a_levels)
        b_level = pwm_to_level(channels[mapping.b - 1], mapping.b_levels)
        index = a_level * mapping.b_levels + b_level
        if 0 <= index < len(mapping.values):
            channels[mapping.channel - 1] = mapping.values[index]

    for channel, value in config.constants.items():
        if 1 <= channel <= CHANNEL_COUNT:
            channels[channel - 1] = value

    return channels
