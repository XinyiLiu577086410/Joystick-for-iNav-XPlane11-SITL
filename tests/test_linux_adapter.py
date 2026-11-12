"""Linux adapter tests that do not require X11."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from hidrx.platform.linux.inav_locator import LinuxInavLocator
from hidrx.platform.linux.keyboard import LinuxKeyboard, normalize_combo
from hidrx.platform.linux.paths import LinuxPaths
from hidrx.platform.linux.platform import LinuxPlatform


class LinuxKeyboardParserTests(unittest.TestCase):
    def test_combos(self) -> None:
        self.assertEqual(normalize_combo("Ctrl+Shift+Space"), "ctrl+shift+space")
        self.assertEqual(normalize_combo("win+a"), "super+a")
        self.assertEqual(normalize_combo("shift"), "shift")
        with self.assertRaises(ValueError):
            normalize_combo("ctrl+")

    def test_wayland_capability(self) -> None:
        old = os.environ.get("XDG_SESSION_TYPE")
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        try:
            caps = LinuxKeyboard().capabilities()
        finally:
            if old is None:
                os.environ.pop("XDG_SESSION_TYPE", None)
            else:
                os.environ["XDG_SESSION_TYPE"] = old
        self.assertFalse(caps.global_keyboard)
        self.assertIn("Wayland", caps.reason)


class LinuxPathAndLocatorTests(unittest.TestCase):
    def test_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = LinuxPaths.for_repo(Path(tmp))
            paths.ensure()
            self.assertTrue(paths.logs_dir.is_dir())

    def test_missing_locator_path(self) -> None:
        self.assertIsNone(LinuxInavLocator().resolve_path(Path("does-not-exist")))

    def test_platform_composition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            platform = LinuxPlatform.for_repo(Path(tmp))
            self.assertEqual(platform.id, "linux")
            self.assertIs(platform.xplane.process, platform.process)


if __name__ == "__main__":
    unittest.main()
