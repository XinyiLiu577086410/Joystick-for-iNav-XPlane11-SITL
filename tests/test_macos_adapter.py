"""macOS adapter tests that do not require macOS."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hidrx.platform.macos.inav_locator import MacOSInavLocator, parse_version_output
from hidrx.platform.macos.keyboard import normalize_combo, resolve_combo
from hidrx.platform.macos.paths import MacOSPaths


class MacOSKeyboardParserTests(unittest.TestCase):
    def test_combos(self) -> None:
        self.assertEqual(normalize_combo("Ctrl+Shift+Space"), "ctrl+shift+space")
        self.assertEqual(normalize_combo("cmd"), "cmd")
        self.assertEqual(resolve_combo("cmd+space").label, "cmd+space")
        with self.assertRaises(ValueError):
            normalize_combo("ctrl+")

    def test_modifier_only(self) -> None:
        combo = resolve_combo("shift")
        self.assertTrue(combo.modifier_only)
        self.assertEqual(combo.label, "shift")


class MacOSPathAndLocatorTests(unittest.TestCase):
    def test_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = MacOSPaths.for_repo(Path(tmp))
            paths.ensure()
            self.assertTrue(paths.runtime_dir.is_dir())

    def test_version_parser(self) -> None:
        self.assertEqual(parse_version_output("INAV/SITL 9.0.0 (abc123)"), ("9.0.0", "abc123"))
        self.assertIsNone(MacOSInavLocator().resolve_path(Path("does-not-exist")))


if __name__ == "__main__":
    unittest.main()
