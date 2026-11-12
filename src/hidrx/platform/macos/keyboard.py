"""macOS keyboard backend using ApplicationServices (no pyobjc dependency)."""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...models import KeyboardCapabilities

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
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "page_up": 116,
    "page_down": 121,
    "home": 115,
    "end": 119,
    "forward_delete": 117,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
    "kp1": 83,
    "kp2": 84,
    "kp3": 85,
    "kp4": 86,
    "kp5": 87,
    "kp6": 88,
    "left_shift": 56,
    "shift": 56,
    "right_shift": 60,
    "left_control": 59,
    "control": 59,
    "ctrl": 59,
    "right_control": 62,
    "left_option": 58,
    "option": 58,
    "alt": 58,
    "right_option": 61,
    "left_command": 55,
    "command": 55,
    "cmd": 55,
    "right_command": 54,
}

_MODIFIER_CODES = {
    "ctrl": (59, 62),
    "shift": (56, 60),
    "alt": (58, 61),
    "cmd": (55, 54),
}
_MODIFIER_ORDER = ("ctrl", "shift", "alt", "cmd")
_MODIFIER_ALIASES = {
    "control": "ctrl",
    "option": "alt",
    "command": "cmd",
    "meta": "cmd",
    "win": "cmd",
}
_MODIFIER_KEYS = {code for codes in _MODIFIER_CODES.values() for code in codes}

_QUARTZ = None


def load_quartz():
    global _QUARTZ
    if _QUARTZ is not None:
        return _QUARTZ
    if sys.platform != "darwin":
        raise RuntimeError("macOS keyboard backend requires macOS")
    path = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    lib = ctypes.cdll.LoadLibrary(path)
    lib.CGEventSourceKeyState.argtypes = [ctypes.c_int32, ctypes.c_uint16]
    lib.CGEventSourceKeyState.restype = ctypes.c_bool
    lib.CGEventSourceFlagsState.argtypes = [ctypes.c_int32]
    lib.CGEventSourceFlagsState.restype = ctypes.c_uint64
    _QUARTZ = lib
    return lib


def _key_down(code: int) -> bool:
    return bool(load_quartz().CGEventSourceKeyState(1, code))


def _modifier_down(name: str) -> bool:
    return any(_key_down(code) for code in _MODIFIER_CODES[name])


def normalize_combo(spec: str) -> str:
    raw = str(spec).split("+")
    if any(not part.strip() for part in raw):
        raise ValueError("empty key binding")
    parts = [part.strip().lower() for part in raw]
    canonical_modifiers = []
    main: Optional[str] = None
    for part in parts:
        part = _MODIFIER_ALIASES.get(part, part)
        if part in _MODIFIER_CODES:
            if main is not None:
                raise ValueError("modifiers must come before the main key")
            if part not in canonical_modifiers:
                canonical_modifiers.append(part)
        else:
            if main is not None:
                raise ValueError("only one main key is allowed")
            main = part
    if main is None:
        return "+".join(name for name in _MODIFIER_ORDER if name in canonical_modifiers)
    if main not in _KEYCODES:
        raise ValueError(f"unknown macOS key name: {main!r}")
    if _KEYCODES[main] in _MODIFIER_KEYS:
        raise ValueError(f"{main!r} is a modifier; put it before a normal key")
    ordered = [name for name in _MODIFIER_ORDER if name in canonical_modifiers]
    return "+".join(ordered + [main])


@dataclass(frozen=True)
class KeyCombo:
    keycode: int
    modifiers: Tuple[str, ...] = ()
    label: str = ""
    modifier_only: bool = False

    def is_down(self) -> bool:
        main = any(_key_down(code) for code in _MODIFIER_CODES[self.label]) if self.modifier_only else _key_down(self.keycode)
        return main and all(_modifier_down(name) for name in self.modifiers)


def resolve_combo(spec: str) -> KeyCombo:
    canonical = normalize_combo(spec)
    if canonical in _MODIFIER_CODES:
        return KeyCombo(keycode=-1, label=canonical, modifier_only=True)
    *modifier_names, main = canonical.split("+")
    return KeyCombo(keycode=_KEYCODES[main], modifiers=tuple(modifier_names), label=canonical)


def _display_key(code: int) -> str:
    for name, value in _KEYCODES.items():
        if value == code and name not in _MODIFIER_KEYS:
            return name
    return f"keycode_{code}"


def _all_released() -> bool:
    return not any(_key_down(code) for code in set(_KEYCODES.values()))


@dataclass
class MacOSKeyboard:
    platform: str = "macos"
    backend: str = "quartz"
    foreground_process: str = "X-Plane"

    def available(self) -> bool:
        try:
            load_quartz()
            return True
        except (OSError, RuntimeError):
            return False

    def capabilities(self) -> KeyboardCapabilities:
        return KeyboardCapabilities(
            global_keyboard=True,
            foreground_gate=False,
            combos=True,
            reason="foreground gating is disabled on macOS (no AppKit dependency)",
        )

    def foreground_matches(self, target: str) -> bool:
        return True

    def validate(self, binding: str) -> None:
        resolve_combo(binding)

    def is_down(self, binding: str) -> bool:
        return resolve_combo(binding).is_down()

    def capture(self, timeout: float = 30.0) -> Optional[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not _all_released():
            time.sleep(0.01)
        pressed_mods: List[str] = []
        held_mods: set = set()
        while time.monotonic() < deadline:
            main = next((code for code in set(_KEYCODES.values()) if code not in _MODIFIER_KEYS and _key_down(code)), None)
            current_mods = {name for name in _MODIFIER_ORDER if _modifier_down(name)}
            if main is not None:
                while not _all_released():
                    if time.monotonic() >= deadline:
                        return None
                    time.sleep(0.01)
                modifiers = [name for name in _MODIFIER_ORDER if name in current_mods]
                return "+".join(modifiers + [_display_key(main)])
            for name in _MODIFIER_ORDER:
                if name in current_mods and name not in held_mods:
                    pressed_mods.append(name)
            held_mods = current_mods
            if not current_mods and pressed_mods:
                return "+".join(name for name in _MODIFIER_ORDER if name in set(pressed_mods))
            time.sleep(0.01)
        return None
