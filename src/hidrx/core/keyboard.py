"""Keyboard-to-channel mapper using the platform KeyboardBackend."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List

from ..actions import KEYBOARD_ACTIONS
from ..constants import CHANNEL_COUNT, MODE_VALUES, PWM_MAX, PWM_MID, PWM_MIN
from ..platform.base import KeyboardBackend
from .config import KeyboardConfig, keyboard_complete


def _approach(current: float, target: float, rate: float, dt: float) -> float:
    step = max(0.0, rate) * dt
    if current < target:
        return min(target, current + step)
    if current > target:
        return max(target, current - step)
    return target


@dataclass
class KeyboardMapper:
    config: KeyboardConfig
    keyboard: KeyboardBackend
    channels: List[int] = field(default_factory=lambda: [PWM_MID] * CHANNEL_COUNT)
    axes: List[float] = field(default_factory=lambda: [PWM_MID, PWM_MID, PWM_MID, PWM_MID])
    throttle: float = PWM_MIN
    armed: bool = False
    mode: int = 0
    wp: bool = False
    previous: Dict[str, bool] = field(default_factory=dict)
    last: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        if not keyboard_complete(self.config):
            raise ValueError("keyboard key bindings are incomplete; run setup keyboard")
        self.channels = [PWM_MID] * CHANNEL_COUNT
        self.channels[2] = PWM_MIN
        self.channels[5] = PWM_MIN
        self.channels[6] = PWM_MIN
        self.channels[7] = MODE_VALUES[0]
        self.channels[8] = PWM_MAX
        self.previous = {action: False for action in KEYBOARD_ACTIONS}

    def restore_channels(self, channels: List[int]) -> None:
        if len(channels) < 8:
            return
        self.axes[0] = channels[0]
        self.axes[1] = channels[1]
        self.axes[2] = channels[2]
        self.axes[3] = channels[3]
        self.throttle = float(channels[2])
        self.armed = channels[6] >= PWM_MID
        self.wp = channels[5] >= PWM_MID
        try:
            self.mode = min(range(6), key=lambda index: abs(MODE_VALUES[index] - channels[7]))
        except (IndexError, ValueError):
            self.mode = 0

    def poll(self) -> List[int]:
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self.last))
        self.last = now
        if self.config.foreground_only and not self.keyboard.foreground_matches(
            self.config.window_process
        ):
            return list(self.channels)

        states = {
            action: bool(self.keyboard.is_down(binding))
            for action, binding in self.config.keys.items()
        }

        if states.get("arm") and not self.previous.get("arm"):
            if not self.armed and self.throttle > 1050:
                pass
            else:
                self.armed = not self.armed
        for index in range(1, 7):
            name = f"mode_{index}"
            if states.get(name) and not self.previous.get(name):
                self.mode = index - 1
        if states.get("nav_wp") and not self.previous.get("nav_wp"):
            self.wp = not self.wp

        roll = PWM_MID
        if states.get("roll_left") and not states.get("roll_right"):
            roll = PWM_MIN
        elif states.get("roll_right") and not states.get("roll_left"):
            roll = PWM_MAX

        pitch = PWM_MID
        if states.get("pitch_up") and not states.get("pitch_down"):
            pitch = PWM_MAX
        elif states.get("pitch_down") and not states.get("pitch_up"):
            pitch = PWM_MIN

        yaw = PWM_MID
        if states.get("yaw_left") and not states.get("yaw_right"):
            yaw = PWM_MIN
        elif states.get("yaw_right") and not states.get("yaw_left"):
            yaw = PWM_MAX

        self.axes[0] = _approach(self.axes[0], roll, self.config.axis_rate, dt)
        self.axes[1] = _approach(self.axes[1], pitch, self.config.axis_rate, dt)
        self.axes[3] = _approach(self.axes[3], yaw, self.config.axis_rate, dt)

        up = states.get("throttle_up", False)
        down = states.get("throttle_down", False)
        if up and not down:
            self.throttle += self.config.throttle_rate * dt
        elif down and not up:
            self.throttle -= self.config.throttle_rate * dt
        self.throttle = max(PWM_MIN, min(PWM_MAX, self.throttle))
        self.axes[2] = self.throttle

        for index in range(4):
            self.channels[index] = int(round(self.axes[index]))
        self.channels[4] = PWM_MID
        self.channels[5] = PWM_MAX if self.wp else PWM_MIN
        self.channels[6] = PWM_MAX if self.armed else PWM_MIN
        self.channels[7] = MODE_VALUES[self.mode]
        self.channels[8] = PWM_MAX
        self.previous = states
        return list(self.channels)

    def close(self) -> None:
        return
