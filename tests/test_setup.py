"""Keyboard setup service tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hidrx.core.config import load_config
from hidrx.platform.fake import FakeKeyboard
from hidrx.services.setup import KeyboardSetupService, SetupError


class KeyboardSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config" / "hid2msp_inav.json"
        self.keyboard = FakeKeyboard(backend="fake")
        self.service = KeyboardSetupService(
            keyboard=self.keyboard,
            config_path=self.path,
            platform_id="fake",
            actions=("arm", "mode_1"),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_capture_all_and_save(self) -> None:
        values = iter(["ctrl+a", "2"])
        keys = self.service.capture_all(lambda action: next(values))
        self.assertEqual(keys, {"arm": "ctrl+a", "mode_1": "2"})
        config = self.service.save(keys)
        self.assertEqual(config.platform, "fake")
        loaded = load_config(self.path)
        self.assertEqual(loaded.keyboard.backend, "fake")
        self.assertEqual(loaded.keyboard.keys["arm"], "ctrl+a")

    def test_duplicate_is_rejected(self) -> None:
        with self.assertRaises(SetupError):
            self.service.capture_all(lambda action: "a")

    def test_missing_capture_is_rejected(self) -> None:
        with self.assertRaises(SetupError):
            self.service.capture_all(lambda action: None)

    def test_save_preserves_hid_mapping(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps(
                {
                    "platform": "fake",
                    "axes": [{"axis": 0, "channel": 1}],
                    "keyboard": {"keys": {}},
                }
            ),
            encoding="utf-8",
        )
        self.service.save({"arm": "ctrl+a", "mode_1": "2"})
        loaded = load_config(self.path)
        self.assertEqual(len(loaded.axes), 1)
        self.assertEqual(loaded.axes[0].channel, 1)

    def test_save_requires_keys(self) -> None:
        with self.assertRaises(SetupError):
            self.service.save({})


if __name__ == "__main__":
    unittest.main()
