"""Windows keyboard backend: global key state and foreground gating."""

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...models import KeyboardCapabilities

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
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "page_up": 0x21,
    "page_down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "left_win": 0x5B,
    "right_win": 0x5C,
    "win": 0x5B,
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
    "semicolon": 0xBA,
    "equals": 0xBB,
    "comma": 0xBC,
    "minus": 0xBD,
    "period": 0xBE,
    "slash": 0xBF,
    "backtick": 0xC0,
    "left_bracket": 0xDB,
    "backslash": 0xDC,
    "right_bracket": 0xDD,
    "quote": 0xDE,
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _VK.setdefault(_letter, ord(_letter.upper()))
for _digit in "0123456789":
    _VK.setdefault(_digit, ord(_digit))

_MODIFIERS = {
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
_LEFT_RIGHT_MODIFIERS = {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def _key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _modifier_down(vk: int) -> bool:
    if vk == 0x5B:
        return _key_down(0x5B) or _key_down(0x5C)
    return _key_down(vk)


def _canonical_modifier(name: str) -> str:
    value = _MODIFIERS[name]
    return {0x11: "ctrl", 0x10: "shift", 0x12: "alt", 0x5B: "win"}[value]


def normalize_combo(spec: str) -> str:
    raw_parts = str(spec).split("+")
    if any(not part.strip() for part in raw_parts):
        raise ValueError("empty key binding")
    parts = [part.strip().lower() for part in raw_parts]
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
                raise ValueError("modifiers must come before the main key")
            modifiers.append(_canonical_modifier(part))
        else:
            if main is not None:
                raise ValueError("only one main key is allowed")
            main = part
    if main is None:
        raise ValueError("combination needs a non-modifier key")
    if main not in _VK:
        raise ValueError(f"unknown Windows key name: {main!r}")
    if _VK[main] in _MODIFIER_VKS:
        raise ValueError(f"{main!r} is a modifier; put it before a normal key")
    canonical = sorted(set(modifiers), key=_MODIFIER_ORDER.index)
    return "+".join(canonical + [main])


@dataclass(frozen=True)
class KeyCombo:
    vk: int
    modifiers: Tuple[int, ...] = ()
    label: str = ""

    def is_down(self) -> bool:
        main = _modifier_down(self.vk) if self.vk in (0x5B, 0x5C) else _key_down(self.vk)
        return main and all(_modifier_down(code) for code in self.modifiers)


def resolve_combo(spec: str) -> KeyCombo:
    canonical = normalize_combo(spec)
    *modifier_names, main_name = canonical.split("+")
    return KeyCombo(
        vk=_VK[main_name],
        modifiers=tuple(_MODIFIERS[name] for name in modifier_names),
        label=canonical,
    )


def _display_key_name(vk: int) -> str:
    preferred = (
        "space",
        "enter",
        "tab",
        "escape",
        "backspace",
        "delete",
        "insert",
        "home",
        "end",
        "page_up",
        "page_down",
        "left",
        "right",
        "up",
        "down",
        "semicolon",
        "equals",
        "comma",
        "minus",
        "period",
        "slash",
        "backtick",
        "left_bracket",
        "right_bracket",
        "backslash",
        "quote",
    )
    for name in preferred:
        if _VK.get(name) == vk:
            return name
    if 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x7B:
        return f"f{vk - 0x6F}"
    return f"vk_{vk:02x}"


def _all_keys_released() -> bool:
    for vk in set(_VK.values()) | {0x5B, 0x5C} | _LEFT_RIGHT_MODIFIERS:
        if _key_down(vk):
            return False
    return True


def is_foreground_process(process_name: str = "X-Plane.exe", title_hint: str = "X-Plane") -> bool:
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


@dataclass
class WindowsKeyboard:
    platform: str = "windows"
    backend: str = "win32"
    foreground_process: str = "X-Plane.exe"

    def available(self) -> bool:
        try:
            return isinstance(int(user32.GetAsyncKeyState(0x41)), int)
        except OSError:
            return False

    def capabilities(self) -> KeyboardCapabilities:
        return KeyboardCapabilities(global_keyboard=True, foreground_gate=True, combos=True)

    def foreground_matches(self, target: str) -> bool:
        return is_foreground_process(target or self.foreground_process)

    def validate(self, binding: str) -> None:
        resolve_combo(binding)

    def is_down(self, binding: str) -> bool:
        return resolve_combo(binding).is_down()

    def capture(self, timeout: float = 30.0) -> Optional[str]:
        capture_keys = sorted(
            {
                vk
                for vk in _VK.values()
                if vk not in _MODIFIER_VKS and vk not in _LEFT_RIGHT_MODIFIERS
            }
        )
        deadline = time.monotonic() + timeout
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
        held_mods: set = set()
        while time.monotonic() < deadline:
            normal = next((vk for vk in capture_keys if _key_down(vk)), None)
            current_mods = {name for name in _MODIFIER_ORDER if _modifier_down(_MODIFIERS[name])}
            if normal is not None:
                modifiers = [name for name in _MODIFIER_ORDER if name in current_mods]
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
            if not current_mods and pressed_mods:
                return "+".join(name for name in _MODIFIER_ORDER if name in set(pressed_mods))
            time.sleep(0.01)
        return None
