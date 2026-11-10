#!/usr/bin/env python3
"""macOS keyboard input for hid2msp.py.

Uses CoreGraphics key-state polling, so the bridge does not need a focused
window.  macOS requires Accessibility / Input Monitoring permission for the
process running hid2msp.py (usually Terminal or the Python interpreter).
"""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List

PWM_MIN, PWM_MID, PWM_MAX = 1000, 1500, 2000
CHANNEL_COUNT = 16

FN_FLAG = 0x00800000  # kCGEventFlagMaskSecondaryFn
# macOS virtual keycodes (ANSI layout).
_KEYCODES: Dict[str, int] = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "kp1": 83,
    "keypad_1": 83,
    "kp2": 84,
    "keypad_2": 84,
    "kp3": 85,
    "keypad_3": 85,
    "kp4": 86,
    "keypad_4": 86,
    "kp5": 87,
    "keypad_5": 87,
    "kp6": 88,
    "keypad_6": 88,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "return": 36,
    "enter": 36,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    "m": 46,
    ".": 47,
    "tab": 48,
    "space": 49,
    "spacebar": 49,
    "`": 50,
    "delete": 51,
    "backspace": 51,
    "escape": 53,
    "esc": 53,
    "right_shift": 60,
    "right_option": 61,
    "right_control": 62,
    "fn": 63,
    "function": 63,
    "left_control": 59,
    "ctrl_l": 59,
    "control_l": 59,
    "left_option": 58,
    "option_l": 58,
    "alt_l": 58,
    "left_command": 55,
    "command_l": 55,
    "cmd_l": 55,
    "right_command": 54,
    "right_cmd": 54,
    "left_shift": 56,
    "shift_l": 56,
    "lshift": 56,
    "shift": 56,
    "caps_lock": 57,
    "capslock": 57,
}

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

_QUARTZ = None


@dataclass
class KeyboardConfig:
    enabled: bool = True
    source: str = "auto"  # auto | hid | keyboard
    axis_rate: float = 600.0  # PWM units per second
    throttle_rate: float = 600.0
    keys: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_KEYS))


def resolve_keycode(name: str) -> int:
    key = str(name).strip().lower()
    if key not in _KEYCODES:
        raise ValueError(f"unknown macOS key name: {name!r}")
    return _KEYCODES[key]


def known_key_names() -> List[str]:
    return sorted(_KEYCODES)


def load_quartz():
    """Load ApplicationServices for CGEventSourceKeyState."""
    global _QUARTZ
    if _QUARTZ is not None:
        return _QUARTZ
    if sys.platform != "darwin":
        raise RuntimeError("keyboard input is implemented for macOS only")

    path = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    try:
        lib = ctypes.cdll.LoadLibrary(path)
    except OSError as exc:
        raise RuntimeError(f"cannot load ApplicationServices: {exc}") from exc

    lib.CGEventSourceKeyState.argtypes = [ctypes.c_int32, ctypes.c_uint16]
    lib.CGEventSourceKeyState.restype = ctypes.c_bool
    lib.CGEventSourceFlagsState.argtypes = [ctypes.c_int32]
    lib.CGEventSourceFlagsState.restype = ctypes.c_uint64
    if hasattr(lib, "AXIsProcessTrusted"):
        lib.AXIsProcessTrusted.argtypes = []
        lib.AXIsProcessTrusted.restype = ctypes.c_bool

    _QUARTZ = lib
    return lib


def accessibility_trusted() -> bool | None:
    try:
        lib = load_quartz()
        if hasattr(lib, "AXIsProcessTrusted"):
            return bool(lib.AXIsProcessTrusted())
    except Exception:
        return None
    return None


def input_monitoring_trusted() -> bool | None:
    """True if this process may monitor keyboard input (Input Monitoring)."""
    try:
        lib = load_quartz()
        if hasattr(lib, "CGPreflightListenEventAccess"):
            lib.CGPreflightListenEventAccess.argtypes = []
            lib.CGPreflightListenEventAccess.restype = ctypes.c_bool
            return bool(lib.CGPreflightListenEventAccess())
    except Exception:
        return None
    return None


def _approach(current: float, target: float, rate: float, dt: float) -> float:
    step = max(0.0, rate) * dt
    if current < target:
        return min(target, current + step)
    if current > target:
        return max(target, current - step)
    return target


class KeyboardInput:
    """Poll macOS key states and produce INAV RC channels."""

    def __init__(self, config: KeyboardConfig) -> None:
        self.config = config
        self.lib = load_quartz()
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

        self.axes = [PWM_MID, PWM_MID, PWM_MID, PWM_MID]  # roll pitch yaw (throttle separate)
        self.throttle = float(PWM_MIN)
        self.armed = False
        self.mode = 0
        self.previous: Dict[str, bool] = {name: False for name in self.keycodes}
        self.last = time.monotonic()
        self.input_monitoring = input_monitoring_trusted()
        self.trusted = self.input_monitoring
        if self.input_monitoring is not True:
            print(
                "keyboard: Input Monitoring is not granted to this Python process; "
                "keys may not be visible. Grant Input Monitoring to Python/Terminal "
                "(not only the hidctl script), then restart the bridge.",
                file=sys.stderr,
            )

    def _key_state(self, action: str, flags: int) -> bool:
        code = self.keycodes.get(action)
        pressed = bool(self.lib.CGEventSourceKeyState(1, code)) if code is not None else False
        if action == "throttle_down" and (flags & FN_FLAG):
            configured = str(self.config.keys.get("throttle_down", "")).lower()
            if configured in ("fn", "function"):
                pressed = True
        return pressed

    def _states(self) -> Dict[str, bool]:
        flags = int(self.lib.CGEventSourceFlagsState(1))
        return {action: self._key_state(action, flags) for action in self.keycodes}

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
                    file=sys.stderr,
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
        print(f"keyboard error: {exc}", file=sys.stderr)
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
