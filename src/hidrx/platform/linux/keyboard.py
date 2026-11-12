"""Linux X11 keyboard backend (Wayland explicitly degraded)."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ...models import KeyboardCapabilities

_X11 = None
_DISPLAY = None

_KEYSYMS: Dict[str, str] = {
    "a": "a",
    "b": "b",
    "c": "c",
    "d": "d",
    "e": "e",
    "f": "f",
    "g": "g",
    "h": "h",
    "i": "i",
    "j": "j",
    "k": "k",
    "l": "l",
    "m": "m",
    "n": "n",
    "o": "o",
    "p": "p",
    "q": "q",
    "r": "r",
    "s": "s",
    "t": "t",
    "u": "u",
    "v": "v",
    "w": "w",
    "x": "x",
    "y": "y",
    "z": "z",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "7": "7",
    "8": "8",
    "9": "9",
    "0": "0",
    "space": "space",
    "tab": "Tab",
    "enter": "Return",
    "return": "Return",
    "backspace": "BackSpace",
    "escape": "Escape",
    "esc": "Escape",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "page_up": "Page_Up",
    "page_down": "Page_Down",
    "home": "Home",
    "end": "End",
    "insert": "Insert",
    "delete": "Delete",
    "minus": "minus",
    "-": "minus",
    "equal": "equal",
    "=": "equal",
    "comma": "comma",
    ",": "comma",
    "period": "period",
    ".": "period",
    "slash": "slash",
    "/": "slash",
    "semicolon": "semicolon",
    ";": "semicolon",
    "apostrophe": "apostrophe",
    "'": "apostrophe",
    "bracketleft": "bracketleft",
    "[": "bracketleft",
    "bracketright": "bracketright",
    "]": "bracketright",
    "backslash": "backslash",
    "\\": "backslash",
    "grave": "grave",
    "`": "grave",
}
for _index in range(1, 13):
    _KEYSYMS[f"f{_index}"] = f"F{_index}"

_MODIFIER_KEYSYMS = {
    "ctrl": ("Control_L", "Control_R"),
    "shift": ("Shift_L", "Shift_R"),
    "alt": ("Alt_L", "Alt_R"),
    "super": ("Super_L", "Super_R"),
}
_MODIFIER_ORDER = ("ctrl", "shift", "alt", "super")
_MODIFIER_ALIASES = {"control": "ctrl", "option": "alt", "win": "super", "cmd": "super", "meta": "super"}


def _load_x11():
    global _X11, _DISPLAY
    if _X11 is not None:
        return _X11
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("Linux keyboard backend does not support Wayland; use X11")
    lib = ctypes.cdll.LoadLibrary("libX11.so.6")
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    lib.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
    lib.XStringToKeysym.restype = ctypes.c_ulong
    lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XKeysymToKeycode.restype = ctypes.c_ubyte
    display = lib.XOpenDisplay(None)
    if not display:
        raise RuntimeError("cannot open X11 display")
    _X11 = lib
    _DISPLAY = display
    return lib


def _display():
    _load_x11()
    return _DISPLAY


def _keymap() -> set:
    buffer = ctypes.create_string_buffer(32)
    _load_x11().XQueryKeymap(_display(), buffer)
    down = set()
    for byte_index, byte in enumerate(buffer.raw):
        for bit in range(8):
            if byte & (1 << bit):
                down.add(byte_index * 8 + bit)
    return down


def _keycode(keysym_name: str) -> int:
    lib = _load_x11()
    keysym = lib.XStringToKeysym(keysym_name.encode())
    if not keysym:
        raise ValueError(f"unknown X11 keysym: {keysym_name}")
    code = lib.XKeysymToKeycode(_display(), keysym)
    if not code:
        raise ValueError(f"X11 key not mapped: {keysym_name}")
    return int(code)


def normalize_combo(spec: str) -> str:
    raw = str(spec).split("+")
    if any(not part.strip() for part in raw):
        raise ValueError("empty key binding")
    parts = [part.strip().lower() for part in raw]
    modifiers: List[str] = []
    main: Optional[str] = None
    for part in parts:
        part = _MODIFIER_ALIASES.get(part, part)
        if part in _MODIFIER_KEYSYMS:
            if main is not None:
                raise ValueError("modifiers must come before the main key")
            if part not in modifiers:
                modifiers.append(part)
        else:
            if main is not None:
                raise ValueError("only one main key is allowed")
            main = part
    if main is None:
        return "+".join(name for name in _MODIFIER_ORDER if name in modifiers)
    if main not in _KEYSYMS:
        raise ValueError(f"unknown Linux key name: {main!r}")
    ordered = [name for name in _MODIFIER_ORDER if name in modifiers]
    return "+".join(ordered + [main])


@dataclass(frozen=True)
class KeyCombo:
    keycode: int
    modifiers: Tuple[str, ...] = ()
    label: str = ""
    modifier_only: bool = False

    def is_down(self) -> bool:
        down = _keymap()
        if self.modifier_only:
            return any(
                _keycode(keysym) in down
                for keysym in _MODIFIER_KEYSYMS[self.label]
            )
        main = self.keycode in down
        modifiers = all(
            any(_keycode(keysym) in down for keysym in _MODIFIER_KEYSYMS[name])
            for name in self.modifiers
        )
        return main and modifiers


def resolve_combo(spec: str) -> KeyCombo:
    canonical = normalize_combo(spec)
    if canonical in _MODIFIER_KEYSYMS:
        return KeyCombo(keycode=-1, label=canonical, modifier_only=True)
    *modifier_names, main = canonical.split("+")
    return KeyCombo(
        keycode=_keycode(_KEYSYMS[main]),
        modifiers=tuple(modifier_names),
        label=canonical,
    )


def _name_for_keycode(code: int) -> str:
    for name, keysym in _KEYSYMS.items():
        try:
            if _keycode(keysym) == code:
                return name
        except ValueError:
            continue
    return f"keycode_{code}"


@dataclass
class LinuxKeyboard:
    platform: str = "linux"
    backend: str = "x11"

    def _wayland(self) -> bool:
        return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

    def available(self) -> bool:
        if self._wayland():
            return False
        try:
            _load_x11()
            return True
        except (OSError, RuntimeError):
            return False

    def capabilities(self) -> KeyboardCapabilities:
        if self._wayland():
            return KeyboardCapabilities(
                global_keyboard=False,
                foreground_gate=False,
                combos=False,
                reason="Wayland has no global key access; use an X11 session",
            )
        gate = shutil.which("xprop") is not None
        return KeyboardCapabilities(global_keyboard=True, foreground_gate=gate, combos=True)

    def foreground_matches(self, target: str) -> bool:
        if not shutil.which("xprop"):
            return True
        try:
            root = subprocess.run(
                ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                capture_output=True,
                text=True,
                errors="replace",
            ).stdout
            window = root.rsplit(" ", 1)[-1].strip()
            if not window or window == "0x0":
                return False
            pid_output = subprocess.run(
                ["xprop", "-id", window, "_NET_WM_PID"],
                capture_output=True,
                text=True,
                errors="replace",
            ).stdout
            if "_NET_WM_PID" not in pid_output:
                return True
            pid = int(pid_output.rsplit("=", 1)[-1].strip())
            comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="replace").strip()
            return target.casefold() in comm.casefold()
        except (OSError, ValueError):
            return True

    def validate(self, binding: str) -> None:
        resolve_combo(binding)

    def is_down(self, binding: str) -> bool:
        return resolve_combo(binding).is_down()

    def capture(self, timeout: float = 30.0) -> Optional[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and any(_keymap()):
            time.sleep(0.01)
        pressed_mods: List[str] = []
        held_mods: set = set()
        while time.monotonic() < deadline:
            down = _keymap()
            modifier_codes = {name: _keycode(keysym) for name, names in _MODIFIER_KEYSYMS.items() for keysym in names}
            modifier_down = {name for name, code in modifier_codes.items() if code in down}
            main = next((code for code in down if code not in set(modifier_codes.values())), None)
            if main is not None:
                while any(_keymap()):
                    if time.monotonic() >= deadline:
                        return None
                    time.sleep(0.01)
                modifiers = [name for name in _MODIFIER_ORDER if name in modifier_down]
                return "+".join(modifiers + [_name_for_keycode(main)])
            for name in _MODIFIER_ORDER:
                if name in modifier_down and name not in held_mods:
                    pressed_mods.append(name)
            held_mods = modifier_down
            if not modifier_down and pressed_mods:
                return "+".join(name for name in _MODIFIER_ORDER if name in set(pressed_mods))
            time.sleep(0.01)
        return None
