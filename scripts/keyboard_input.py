#!/usr/bin/env python3
"""Windows keyboard input for hid2msp.py.

Polls global key state with ``GetAsyncKeyState``, so the bridge does not need a
focused window and needs no special permission.  Windows-only: the macOS
implementation (CoreGraphics + Input Monitoring) lives on the ``main`` branch.
"""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass, field
from typing import Dict, List

PWM_MIN, PWM_MID, PWM_MAX = 1000, 1500, 2000
CHANNEL_COUNT = 16

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

# Windows virtual-key codes (https://learn.microsoft.com/windows/win32/inputdev/virtual-key-codes)
_VK: Dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "control": 0x11,
    "ctrl": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "caps_lock": 0x14,
    "capslock": 0x14,
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "spacebar": 0x20,
    "page_up": 0x21,
    "page_down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "print_screen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "left_win": 0x5B,
    "right_win": 0x5C,
    "num0": 0x60,
    "num1": 0x61,
    "num2": 0x62,
    "num3": 0x63,
    "num4": 0x64,
    "num5": 0x65,
    "num6": 0x66,
    "num7": 0x67,
    "num8": 0x68,
    "num9": 0x69,
    "multiply": 0x6A,
    "add": 0x6B,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    "num_lock": 0x90,
    "scroll_lock": 0x91,
    "left_shift": 0xA0,
    "right_shift": 0xA1,
    "left_control": 0xA2,
    "left_ctrl": 0xA2,
    "right_control": 0xA3,
    "right_ctrl": 0xA3,
    "left_alt": 0xA4,
    "left_option": 0xA4,  # macOS alias kept so old configs validate
    "right_alt": 0xA5,
    "right_option": 0xA5,
    "semicolon": 0xBA,
    ";": 0xBA,
    "equals": 0xBB,
    "=": 0xBB,
    "comma": 0xBC,
    ",": 0xBC,
    "minus": 0xBD,
    "-": 0xBD,
    "period": 0xBE,
    ".": 0xBE,
    "slash": 0xBF,
    "/": 0xBF,
    "backtick": 0xC0,
    "`": 0xC0,
    "left_bracket": 0xDB,
    "[": 0xDB,
    "backslash": 0xDC,
    "\\": 0xDC,
    "right_bracket": 0xDD,
    "]": 0xDD,
    "quote": 0xDE,
    "'": 0xDE,
}

for _letter in "abcdefghijklmnopqrstuvwxyz":
    _VK.setdefault(_letter, ord(_letter.upper()))
for _digit in "0123456789":
    _VK.setdefault(_digit, ord(_digit))

DEFAULT_KEYS: Dict[str, str] = {
    "roll_left": "a",
    "roll_right": "d",
    "pitch_up": "w",
    "pitch_down": "s",
    "yaw_left": "q",
    "yaw_right": "e",
    "arm": "space",
    "throttle_up": "left_shift",
    "throttle_down": "left_control",
    "mode_1": "1",
    "mode_2": "2",
    "mode_3": "3",
    "mode_4": "4",
    "mode_5": "5",
    "mode_6": "6",
}

MODE_VALUES = (1000, 1200, 1400, 1600, 1800, 2000)


@dataclass
class KeyboardConfig:
    enabled: bool = True
    source: str = "auto"  # auto | hid | keyboard
    axis_rate: float = 600.0  # PWM units per second
    throttle_rate: float = 600.0
    keys: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_KEYS))


def resolve_keycode(name: str) -> int:
    key = str(name).strip().lower()
    if key not in _VK:
        raise ValueError(f"unknown Windows key name: {name!r}")
    return _VK[key]


def known_key_names() -> List[str]:
    return sorted(_VK)


def input_available() -> bool:
    """True when this process can read global key state."""
    try:
        return isinstance(int(user32.GetAsyncKeyState(0x41)), int)
    except OSError:
        return False


def _key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _approach(current: float, target: float, rate: float, dt: float) -> float:
    step = max(0.0, rate) * dt
    if current < target:
        return min(target, current + step)
    if current > target:
        return max(target, current - step)
    return target


class KeyboardInput:
    """Poll Windows key states and produce INAV RC channels."""

    def __init__(self, config: KeyboardConfig) -> None:
        self.config = config
        self.keycodes: Dict[str, int] = {}
        for action, key in config.keys.items():
            try:
                self.keycodes[action] = resolve_keycode(key)
            except ValueError as exc:
                raise RuntimeError(f"keyboard.{action}: {exc}") from exc

        self.channels = [PWM_MID] * CHANNEL_COUNT
        self.channels[2] = PWM_MIN  # throttle
        self.channels[5] = PWM_MIN  # CH6 NAV WP off
        self.channels[6] = PWM_MIN  # CH7 disarmed
        self.channels[7] = MODE_VALUES[0]  # CH8 ANGLE
        self.channels[8] = PWM_MAX  # CH9 NAV LAUNCH

        self.axes = [PWM_MID, PWM_MID, PWM_MID, PWM_MID]
        self.throttle = float(PWM_MIN)
        self.armed = False
        self.mode = 0
        self.previous: Dict[str, bool] = {name: False for name in self.keycodes}
        self.last = time.monotonic()

        if not input_available():
            raise RuntimeError(
                "GetAsyncKeyState is unavailable; keyboard input cannot be read "
                "from this session"
            )

    def _states(self) -> Dict[str, bool]:
        return {action: _key_down(code) for action, code in self.keycodes.items()}

    def poll(self) -> List[int]:
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self.last))
        self.last = now
        states = self._states()

        # Arm toggles on press edge; refuse to arm above low throttle.
        if states.get("arm") and not self.previous.get("arm"):
            if not self.armed and self.throttle > 1050:
                print(
                    "keyboard: throttle is not low; lower it before arming",
                    flush=True,
                )
            else:
                self.armed = not self.armed

        # Number keys select one of six modes on press edge.
        for index in range(1, 7):
            name = f"mode_{index}"
            if states.get(name) and not self.previous.get(name):
                self.mode = index - 1

        roll_target = PWM_MID
        if states.get("roll_left") and not states.get("roll_right"):
            roll_target = PWM_MIN
        elif states.get("roll_right") and not states.get("roll_left"):
            roll_target = PWM_MAX

        pitch_target = PWM_MID
        if states.get("pitch_up") and not states.get("pitch_down"):
            pitch_target = PWM_MAX
        elif states.get("pitch_down") and not states.get("pitch_up"):
            pitch_target = PWM_MIN

        yaw_target = PWM_MID
        if states.get("yaw_left") and not states.get("yaw_right"):
            yaw_target = PWM_MIN
        elif states.get("yaw_right") and not states.get("yaw_left"):
            yaw_target = PWM_MAX

        self.axes[0] = _approach(self.axes[0], roll_target, self.config.axis_rate, dt)
        self.axes[1] = _approach(self.axes[1], pitch_target, self.config.axis_rate, dt)
        self.axes[3] = _approach(self.axes[3], yaw_target, self.config.axis_rate, dt)

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
        self.channels[5] = PWM_MIN
        self.channels[6] = PWM_MAX if self.armed else PWM_MIN
        self.channels[7] = MODE_VALUES[self.mode]
        self.channels[8] = PWM_MAX

        self.previous = states
        return list(self.channels)

    def close(self) -> None:
        return


def monitor_keyboard(config: KeyboardConfig) -> int:
    """Print live keyboard-derived channels until Ctrl-C."""
    try:
        keyboard = KeyboardInput(config)
    except Exception as exc:
        print(f"keyboard error: {exc}", flush=True)
        return 2

    print("keyboard: press keys; Ctrl-C to stop.")
    try:
        while True:
            channels = keyboard.poll()
            print(
                "\rch=" + " ".join(str(v) for v in channels[:9]),
                end="",
                flush=True,
            )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
    finally:
        keyboard.close()
    return 0
