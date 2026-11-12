"""macOS adapters."""

from .inav_locator import MacOSInavLocator
from .keyboard import MacOSKeyboard, normalize_combo, resolve_combo
from .paths import MacOSPaths
from .platform import MacOSPlatform
from .xplane import MacOSXPlane

__all__ = [
    "MacOSInavLocator",
    "MacOSKeyboard",
    "MacOSPaths",
    "MacOSPlatform",
    "MacOSXPlane",
    "normalize_combo",
    "resolve_combo",
]
