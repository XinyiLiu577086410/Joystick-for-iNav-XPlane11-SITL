"""Platform factory tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from hidrx.platform.factory import create_platform, platform_id_for


class FactoryTests(unittest.TestCase):
    def test_platform_ids(self) -> None:
        self.assertEqual(platform_id_for("win32"), "windows")
        self.assertEqual(platform_id_for("darwin"), "macos")
        self.assertEqual(platform_id_for("linux"), "linux")

    @unittest.skipUnless(sys.platform == "win32", "Windows implementation only")
    def test_create_windows_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            platform = create_platform(Path(tmp))
            self.assertEqual(platform.id, "windows")
            self.assertEqual(platform.paths.repo_root, Path(tmp))

    @unittest.skipUnless(sys.platform in ("darwin", "linux"), "POSIX implementation only")
    def test_create_posix_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            platform = create_platform(Path(tmp))
            self.assertIn(platform.id, ("macos", "linux"))
            self.assertEqual(platform.paths.repo_root, Path(tmp))


if __name__ == "__main__":
    unittest.main()
