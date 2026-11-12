"""Fake platform contract smoke test."""

from __future__ import annotations

import unittest
from pathlib import Path

from hidrx.models import ProcessSpec
from hidrx.platform.fake import FakePlatform


class FakePlatformTests(unittest.TestCase):
    def test_process_lifecycle(self) -> None:
        platform = FakePlatform()
        handle = platform.process.spawn(
            ProcessSpec(argv=("inav_SITL",), cwd=Path("."), log_path=Path("sitl.log"))
        )
        self.assertTrue(platform.process.is_alive(handle))
        platform.process.stop(handle)
        self.assertFalse(platform.process.is_alive(handle))

    def test_keyboard_and_inav(self) -> None:
        platform = FakePlatform()
        platform.keyboard.bindings["arm"] = True
        platform.keyboard.captured = "ctrl+a"
        self.assertTrue(platform.keyboard.is_down("arm"))
        self.assertEqual(platform.keyboard.capture(1.0), "ctrl+a")
        self.assertEqual(platform.inav.discover(), [])


if __name__ == "__main__":
    unittest.main()
