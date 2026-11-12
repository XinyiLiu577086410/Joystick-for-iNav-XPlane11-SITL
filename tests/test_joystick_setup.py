"""Joystick setup detection and save tests."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import List, Sequence, Tuple

from hidrx.core.config import load_config
from hidrx.services.joystick_setup import (
    JoystickSetupService,
    detect_axis,
    detect_button,
)
from hidrx.services.setup import SetupError


class FakeGamepad:
    name = "fake"
    num_axes = 5
    num_buttons = 2

    def __init__(self, frames: List[Tuple[Sequence[float], Sequence[int]]]) -> None:
        self.frames = frames

    def snapshot(self):
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0]

    def close(self):
        pass


class DetectionTests(unittest.TestCase):
    def test_detect_axis(self) -> None:
        device = FakeGamepad([([0.0, 0.0], [0, 0]), ([0.0, 0.9], [0, 0])])
        axis, delta = detect_axis(device, timeout=1.0, hold_seconds=0.0)
        self.assertEqual(axis, 1)
        self.assertAlmostEqual(delta, 0.9)

    def test_detect_button(self) -> None:
        device = FakeGamepad(
            [([0.0], [0, 0]), ([0.0], [0, 1]), ([0.0], [0, 0])]
        )
        self.assertEqual(detect_button(device, timeout=1.0), 1)

    def test_detect_button_already_held_is_not_auto_accepted(self) -> None:
        device = FakeGamepad([([0.0], [1, 0])])
        with self.assertRaises(SetupError):
            detect_button(device, timeout=0.1)

    def test_detect_button_requires_return(self) -> None:
        device = FakeGamepad([([0.0], [1, 0]), ([0.0], [0, 0])])
        with self.assertRaises(SetupError):
            detect_button(device, timeout=0.1)

    def test_timeout(self) -> None:
        device = FakeGamepad([([0.0], [0, 0])])
        with self.assertRaises(SetupError):
            detect_axis(device, timeout=0.05)

    def test_detect_axis_requires_hold(self) -> None:
        device = FakeGamepad([([0.0], [0]), ([1.0], [0])])
        started = time.monotonic()
        axis, delta = detect_axis(device, timeout=1.0, hold_seconds=0.2)
        self.assertEqual(axis, 0)
        self.assertGreaterEqual(time.monotonic() - started, 0.18)

    def test_excluded_axis_is_ignored(self) -> None:
        device = FakeGamepad(
            [
                ([0.0, 0.0], [0, 0]),
                ([0.3, 0.9], [0, 0]),
            ]
        )
        axis, _ = detect_axis(
            device,
            timeout=1.0,
            threshold=0.2,
            hold_seconds=0.0,
            exclude_axes={1},
        )
        self.assertEqual(axis, 0)


class SetupSaveTests(unittest.TestCase):
    def _frames(self):
        return [
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # roll baseline
            ([-0.9, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # roll left
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # roll baseline
            ([0.9, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # roll right
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # pitch baseline
            ([0.0, 0.9, 0.0, 0.0, 0.0], [0, 0]),  # pitch up
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # pitch baseline
            ([0.0, -0.9, 0.0, 0.0, 0.0], [0, 0]),  # pitch down
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # yaw baseline
            ([0.0, 0.0, -0.9, 0.0, 0.0], [0, 0]),  # yaw left
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # yaw baseline
            ([0.0, 0.0, 0.9, 0.0, 0.0], [0, 0]),  # yaw right
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # throttle baseline
            ([0.0, 0.0, 0.0, -0.9, 0.0], [0, 0]),  # throttle low
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # throttle baseline
            ([0.0, 0.0, 0.0, 0.9, 0.0], [0, 0]),  # throttle high
            ([0.0, 0.0, 0.0, 0.0, 0.0], [0, 0]),  # mode baseline
            ([0.0, 0.0, 0.0, 0.0, 0.8], [0, 0]),  # mode
            ([0.0, 0.0], [0, 0]),  # NAV WP low
            ([0.0, 0.0], [0, 1]),  # NAV WP high
            ([0.0, 0.0], [0, 0]),  # arm baseline
            ([0.0, 0.0], [1, 0]),  # arm press
            ([0.0, 0.0], [0, 0]),  # arm release/return
        ]

    def test_capture_and_save_preserves_keyboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config" / "hid2msp_inav.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "platform": "fake",
                        "keyboard": {"backend": "fake", "keys": {"arm": "ctrl+a"}},
                    }
                ),
                encoding="utf-8",
            )
            service = JoystickSetupService(
                path,
                "fake",
                "fake",
                timeout=1.0,
                hold_seconds=0.0,
            )
            confirmed = []
            config = service.capture(
                FakeGamepad(self._frames()),
                confirm=lambda text: confirmed.append(text),
            )
            self.assertEqual([item.channel for item in config.axes], [1, 2, 4, 3, 8])
            self.assertEqual(config.axes[-1].kind, "multi")
            self.assertEqual([item.channel for item in config.buttons], [6, 7])
            self.assertEqual(len(confirmed), 15)
            service.save(config)
            loaded = load_config(path)
            self.assertEqual(loaded.keyboard.keys["arm"], "ctrl+a")
            self.assertEqual(len(loaded.axes), 5)


if __name__ == "__main__":
    unittest.main()
