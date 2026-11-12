#!/usr/bin/env python3
"""Windows keyboard input for hid2msp.py.

Polls global key state with ``GetAsyncKeyState``, so the bridge does not need a
focused window and needs no special permission.  Keyboard input is only enabled
while X-Plane is the foreground window (``keyboard.foreground_only``), and each
action can be a single key or a modifier combination such as
``ctrl+shift+space``.

Windows-only: the macOS implementation (CoreGraphics + Input Monitoring) lives
on the ``main`` branch.
"""

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

PWM_MIN, PWM_MID, PWM_MAX = 1000, 1500, 2000
CHANNEL_COUNT = 16

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_wchar_p,
    ctypes.POINTER(ctypes.c_ulong),
]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_int

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

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
    "win": 0x5B,
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

# Modifier names usable in a combo.  Generic VK_CONTROL / VK_SHIFT / VK_MENU
# match either side; Win is checked against both left and right.
_MODIFIERS: Dict[str, int] = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "option": 0x12,
    "win": 0x5B,
    "windows": 0x5B,
    "cmd": 0x5B,
    "meta": 0x5B,
}
_MODIFIER_ORDER = ("ctrl", "shift", "alt", "win")
_MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C}
_WIN_VKS = (0x5B, 0x5C)

KEYBOARD_ACTIONS: Tuple[str, ...] = (
    "roll_left",
    "roll_right",
    "pitch_up",
    "pitch_down",
    "yaw_left",
    "yaw_right",
    "throttle_up",
    "throttle_down",
    "arm",
    "mode_1",
    "mode_2",
    "mode_3",
    "mode_4",
    "mode_5",
    "mode_6",
)

MODE_VALUES = (1000, 1200, 1400, 1600, 1800, 2000)


def _key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _modifier_down(vk: int) -> bool:
    if vk == 0x5B:  # Win: either side
        return any(_key_down(code) for code in _WIN_VKS)
    return _key_down(vk)


def _display_key_name(vk: int) -> str:
    preferred = (
        "space", "enter", "tab", "escape", "backspace", "delete", "insert",
        "home", "end", "page_up", "page_down", "left", "right", "up", "down",
        "semicolon", "equals", "comma", "minus", "period", "slash", "backtick",
        "left_bracket", "right_bracket", "backslash", "quote",
        "multiply", "add", "subtract", "decimal", "divide",
    )
    for name in preferred:
        if _VK.get(name) == vk:
            return name
    if 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"num{vk - 0x60}"
    if 0x70 <= vk <= 0x7B:
        return f"f{vk - 0x6F}"
    return f"vk_{vk:02x}"


@dataclass(frozen=True)
class KeyCombo:
    """A main key plus zero or more modifier keys."""

    vk: int
    modifiers: Tuple[int, ...] = ()
    label: str = ""

    def is_down(self) -> bool:
        if self.vk in (0x5B, 0x5C):
            main_down = _modifier_down(self.vk)
        else:
            main_down = _key_down(self.vk)
        if not main_down:
            return False
        return all(_modifier_down(code) for code in self.modifiers)


def _canonical_modifier(name: str) -> str:
    value = _MODIFIERS[name]
    return {0x11: "ctrl", 0x10: "shift", 0x12: "alt", 0x5B: "win"}[value]


def normalize_combo(spec: str) -> str:
    """Return a canonical ``ctrl+shift+space`` style binding.

    A binding may be a single key, a modifier combination such as
    ``ctrl+shift``, or modifiers plus one normal key.  Raises ValueError for
    unknown keys or more than one main key.
    """
    parts = [part.strip().lower() for part in str(spec).split("+") if part.strip()]
    if not parts:
        raise ValueError("empty key binding")

    if all(part in _MODIFIERS for part in parts):
        modifiers = {_canonical_modifier(part) for part in parts}
        return "+".join(name for name in _MODIFIER_ORDER if name in modifiers)

    modifiers: List[str] = []
    main: Optional[str] = None
    for part in parts:
        if part in _MODIFIERS:
            if main is not None:
                raise ValueError(f"modifier {part!r} must come before the main key")
            modifiers.append(_canonical_modifier(part))
        else:
            if main is not None:
                raise ValueError("a combination can only contain one main key")
            main = part

    if main is None:
        raise ValueError("combination needs a non-modifier key")
    if main not in _VK:
        raise ValueError(f"unknown Windows key name: {main!r}")
    if _VK[main] in _MODIFIER_VKS:
        raise ValueError(f"{main!r} is a modifier; put it before a normal key")

    canonical_mods = sorted(set(modifiers), key=_MODIFIER_ORDER.index)
    return "+".join(canonical_mods + [main])


def resolve_combo(spec: str) -> KeyCombo:
    canonical = normalize_combo(spec)
    *modifier_names, main_name = canonical.split("+")
    vk = _VK[main_name]
    modifiers = tuple(_MODIFIERS[name] for name in modifier_names)
    return KeyCombo(vk=vk, modifiers=modifiers, label=canonical)


def resolve_keycode(name: str) -> int:
    """Resolve a single key name (kept for older callers and validators)."""
    combo = resolve_combo(name)
    if combo.modifiers:
        raise ValueError(f"{name!r} is a combination, not a single key")
    return combo.vk


def known_key_names() -> List[str]:
    return sorted(_VK)


def input_available() -> bool:
    """True when this process can read global key state."""
    try:
        return isinstance(int(user32.GetAsyncKeyState(0x41)), int)
    except OSError:
        return False


def is_foreground_process(process_name: str = "X-Plane.exe", title_hint: str = "X-Plane") -> bool:
    """True when the foreground window belongs to ``process_name``.

    Falls back to the window title when the process cannot be queried (for
    example when X-Plane runs elevated and the bridge does not).
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False

    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid.value)
        if handle:
            try:
                size = ctypes.c_ulong(1024)
                buffer = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    if os.path.basename(buffer.value).casefold() == process_name.casefold():
                        return True
            finally:
                kernel32.CloseHandle(handle)

    if title_hint:
        title = ctypes.create_unicode_buffer(512)
        length = user32.GetWindowTextW(hwnd, title, len(title))
        if length:
            lowered = title.value.casefold()
            if title_hint.casefold() in lowered or "x-system" in lowered:
                return True
    return False


def _all_keys_released() -> bool:
    for vk in set(_VK.values()) | {0x5B, 0x5C}:
        if _key_down(vk):
            return False
    return True


def capture_combo(timeout: float = 30.0) -> Optional[str]:
    """Wait for the user to press keys and return a canonical combo string.

    Modifiers held when the main key goes down become part of the combo.  The
    function returns once every involved key has been released.
    """
    capture_keys = sorted(
        {
            vk
            for vk in _VK.values()
            if vk not in _MODIFIER_VKS and vk not in (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5)
        }
    )
    print("Press the key combination (hold modifiers, then press the main key)...", flush=True)
    deadline = time.monotonic() + timeout

    # The Enter used to confirm the wizard prompt may still be held.  Wait for
    # a short quiet period so it is not captured as the binding.
    quiet_since: Optional[float] = None
    while time.monotonic() < deadline:
        if _all_keys_released():
            if quiet_since is None:
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since >= 0.15:
                break
        else:
            quiet_since = None
        time.sleep(0.01)

    pressed_mods: List[str] = []
    held_mods: set[str] = set()
    while time.monotonic() < deadline:
        normal = next((vk for vk in capture_keys if _key_down(vk)), None)
        current_mods = {
            name for name in _MODIFIER_ORDER if _modifier_down(_MODIFIERS[name])
        }

        if normal is not None:
            modifiers = [name for name in _MODIFIER_ORDER if name in current_mods]

            # Wait for a full release so the next capture does not see the same key.
            while any(_key_down(vk) for vk in capture_keys) or any(
                _modifier_down(vk) for vk in (0x11, 0x10, 0x12, 0x5B)
            ):
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.01)

            return "+".join(modifiers + [_display_key_name(normal)])

        for name in _MODIFIER_ORDER:
            if name in current_mods and name not in held_mods:
                pressed_mods.append(name)
        held_mods = current_mods

        # A modifier pressed and released by itself (Shift, Ctrl, ...) is a
        # valid binding; a modifier held while a normal key goes down is a
        # combination and was handled above.
        if not current_mods and pressed_mods:
            unique = [name for name in _MODIFIER_ORDER if name in set(pressed_mods)]
            return "+".join(unique)

        time.sleep(0.01)
    return None


@dataclass
class KeyboardConfig:
    enabled: bool = True
    source: str = "auto"  # auto | hid | keyboard
    axis_rate: float = 600.0  # PWM units per second
    throttle_rate: float = 600.0
    keys: Dict[str, str] = field(default_factory=dict)
    foreground_only: bool = True
    window_process: str = "X-Plane.exe"


def _approach(current: float, target: float, rate: float, dt: float) -> float:
    step = max(0.0, rate) * dt
    if current < target:
        return min(target, current + step)
    if current > target:
        return max(target, current - step)
    return target


class KeyboardInput:
    """Poll Windows key states and produce INAV RC channels."""

    FOREGROUND_RECHECK_SECONDS = 0.5

    def __init__(self, config: KeyboardConfig) -> None:
        self.config = config
        missing = [action for action in KEYBOARD_ACTIONS if action not in config.keys]
        if missing:
            raise RuntimeError(
                "keyboard is not configured (missing: "
                + ", ".join(missing)
                + "); run: .\\hidctl.cmd setup keyboard"
            )

        self.combos: Dict[str, KeyCombo] = {}
        for action, key in config.keys.items():
            try:
                self.combos[action] = resolve_combo(key)
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
        self.previous: Dict[str, bool] = {name: False for name in self.combos}
        self.last = time.monotonic()
        self._foreground_ok: Optional[bool] = None
        self._foreground_checked_at = 0.0
        self._paused_reported = False

        if not input_available():
            raise RuntimeError(
                "GetAsyncKeyState is unavailable; keyboard input cannot be read "
                "from this session"
            )

    def _is_active(self) -> bool:
        if not self.config.foreground_only:
            return True
        now = time.monotonic()
        if (
            self._foreground_ok is None
            or now - self._foreground_checked_at >= self.FOREGROUND_RECHECK_SECONDS
        ):
            self._foreground_ok = is_foreground_process(self.config.window_process)
            self._foreground_checked_at = now
        return bool(self._foreground_ok)

    def _states(self) -> Dict[str, bool]:
        return {action: combo.is_down() for action, combo in self.combos.items()}

    def _build_channels(self) -> List[int]:
        for index in range(4):
            self.channels[index] = int(round(self.axes[index]))
        self.channels[4] = PWM_MID
        self.channels[5] = PWM_MIN
        self.channels[6] = PWM_MAX if self.armed else PWM_MIN
        self.channels[7] = MODE_VALUES[self.mode]
        self.channels[8] = PWM_MAX
        return list(self.channels)

    def poll(self) -> List[int]:
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self.last))
        self.last = now

        if not self._is_active():
            # Ignore input while another application is focused, but remember
            # which keys are physically held so returning to X-Plane with a key
            # down does not fire a spurious press edge.
            self.previous = self._states()
            self.axes[0] = _approach(self.axes[0], PWM_MID, self.config.axis_rate, dt)
            self.axes[1] = _approach(self.axes[1], PWM_MID, self.config.axis_rate, dt)
            self.axes[3] = _approach(self.axes[3], PWM_MID, self.config.axis_rate, dt)
            if not self._paused_reported:
                print(
                    "keyboard: X-Plane is not the foreground window - input paused",
                    flush=True,
                )
                self._paused_reported = True
            return self._build_channels()

        if self._paused_reported:
            print("keyboard: X-Plane is active - input resumed", flush=True)
            self._paused_reported = False

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
        # INAV commands nose-up with a *low* CH2 value (the same convention as
        # the HID setup wizard), so "pitch up" must drive the channel down.
        if states.get("pitch_up") and not states.get("pitch_down"):
            pitch_target = PWM_MIN
        elif states.get("pitch_down") and not states.get("pitch_up"):
            pitch_target = PWM_MAX

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

        self.previous = states
        return self._build_channels()

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
