"""Startup guard and configuration tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hidrx.actions import KEYBOARD_ACTIONS
from hidrx.core.config import BridgeConfig, ConfigError, config_from_dict, load_config, validate_config
from hidrx.core.startup import StartupError, require_ready
from hidrx.platform.fake import FakeKeyboard


class RejectingKeyboard(FakeKeyboard):
    def validate(self, binding: str) -> None:
        raise ValueError("unknown key")


def complete_keyboard() -> dict:
    return {action: "a" for action in KEYBOARD_ACTIONS}


class ConfigTests(unittest.TestCase):
    def test_load_requires_platform_and_has_no_default_mapping(self) -> None:
        config = config_from_dict({"platform": "fake", "keyboard": {"keys": {}}})
        self.assertEqual(config.axes, [])
        self.assertEqual(config.keyboard.keys, {})
        self.assertIn("platform: missing", validate_config(BridgeConfig()))
        self.assertTrue(any("no HID mapping" in item for item in validate_config(config)))

    def test_old_source_hid_maps_to_gamepad(self) -> None:
        config = config_from_dict(
            {"platform": "fake", "keyboard": {"source": "hid", "keys": complete_keyboard()}}
        )
        self.assertEqual(config.keyboard.source, "gamepad")

    def test_load_from_file(self) -> None:
        data = {"platform": "fake", "port": 6000, "keyboard": {"keys": complete_keyboard()}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.platform, "fake")
        self.assertEqual(config.port, 6000)

    def test_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)


class StartupTests(unittest.TestCase):
    def test_platform_mismatch_rejected(self) -> None:
        config = config_from_dict(
            {"platform": "windows", "keyboard": {"backend": "win32", "keys": complete_keyboard()}}
        )
        with self.assertRaises(StartupError):
            require_ready(config, platform_id="macos", backend_id="quartz")

    def test_keyboard_only_auto(self) -> None:
        config = config_from_dict(
            {"platform": "fake", "keyboard": {"backend": "fake", "keys": complete_keyboard()}}
        )
        plan = require_ready(config, "fake", "fake", "auto")
        self.assertEqual(plan.input_source, "auto")
        self.assertTrue(plan.keyboard_fallback)

    def test_gamepad_mode_requires_mapping(self) -> None:
        config = config_from_dict(
            {"platform": "fake", "keyboard": {"backend": "fake", "keys": complete_keyboard()}}
        )
        with self.assertRaises(StartupError):
            require_ready(config, "fake", "fake", "gamepad")

    def test_auto_without_mapping_rejected(self) -> None:
        config = config_from_dict({"platform": "fake", "keyboard": {"keys": {}}})
        with self.assertRaises(StartupError):
            require_ready(config, "fake", "fake", "auto")

    def test_invalid_binding_rejected_by_backend(self) -> None:
        config = config_from_dict(
            {"platform": "fake", "keyboard": {"backend": "fake", "keys": complete_keyboard()}}
        )
        with self.assertRaises(StartupError):
            require_ready(config, "fake", "fake", "auto", keyboard=RejectingKeyboard())


if __name__ == "__main__":
    unittest.main()
