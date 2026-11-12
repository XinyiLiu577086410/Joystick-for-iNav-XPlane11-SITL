"""Bridge runner and keyboard mapper tests."""

from __future__ import annotations

import unittest
from typing import List

from hidrx.actions import KEYBOARD_ACTIONS
from hidrx.core.bridge import BridgeRunner
from hidrx.core.channels import AxisMap
from hidrx.core.config import BridgeConfig, KeyboardConfig
from hidrx.core.keyboard import KeyboardMapper
from hidrx.platform.fake import FakeKeyboard


def keyboard_config(source: str = "auto") -> KeyboardConfig:
    return KeyboardConfig(
        enabled=True,
        source=source,
        keys={action: action for action in KEYBOARD_ACTIONS},
        foreground_only=False,
    )


class FakeLink:
    def __init__(self) -> None:
        self.sent: List[List[int]] = []
        self.last_error = ""
        self.connected = 0

    def send_raw_rc(self, channels) -> bool:
        self.sent.append(list(channels))
        return True

    def connect(self) -> bool:
        self.connected += 1
        return True

    def close(self) -> None:
        pass


class GoodGamepad:
    name = "good"
    num_axes = 1
    num_buttons = 1

    def snapshot(self):
        return [0.0], [0]

    def close(self):
        pass


class BadGamepad:
    name = "bad"
    num_axes = 1
    num_buttons = 1

    def snapshot(self):
        raise ValueError("unplugged")

    def close(self):
        pass


class BridgeRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = BridgeConfig(
            platform="fake",
            axes=[AxisMap(axis=0, channel=1)],
            keyboard=keyboard_config(),
        )
        self.keyboard = FakeKeyboard(backend="fake")

    def test_gamepad_sends_frames(self) -> None:
        link = FakeLink()
        runner = BridgeRunner(
            link=link,
            config=self.config,
            input_source="auto",
            keyboard_backend=self.keyboard,
            gamepad_factory=GoodGamepad,
            keyboard_factory=lambda: KeyboardMapper(self.config.keyboard, self.keyboard),
        )
        self.assertEqual(runner.run(max_frames=2), 0)
        self.assertEqual(len(link.sent), 2)

    def test_disconnect_falls_back_to_keyboard(self) -> None:
        link = FakeLink()
        calls = {"count": 0}

        def factory():
            calls["count"] += 1
            if calls["count"] == 1:
                return BadGamepad()
            raise ValueError("still gone")

        runner = BridgeRunner(
            link=link,
            config=self.config,
            input_source="auto",
            keyboard_backend=self.keyboard,
            gamepad_factory=factory,
            keyboard_factory=lambda: KeyboardMapper(self.config.keyboard, self.keyboard),
        )
        self.assertEqual(runner.run(max_frames=1), 0)
        self.assertEqual(len(link.sent), 1)
        runner.close()

    def test_gamepad_loss_waits_without_sending(self) -> None:
        link = FakeLink()

        def factory():
            raise ValueError("not present")

        runner = BridgeRunner(
            link=link,
            config=self.config,
            input_source="gamepad",
            keyboard_backend=self.keyboard,
            gamepad_factory=factory,
            keyboard_factory=lambda: KeyboardMapper(self.config.keyboard, self.keyboard),
        )
        runner.start()
        self.assertTrue(runner.waiting)
        self.assertEqual(link.sent, [])


class KeyboardMapperTests(unittest.TestCase):
    def test_arm_and_mode_edges(self) -> None:
        config = BridgeConfig(
            platform="fake",
            keyboard=keyboard_config("keyboard"),
        )
        keyboard = FakeKeyboard(backend="fake", bindings={"arm": True, "mode_2": True})
        mapper = KeyboardMapper(config.keyboard, keyboard)
        channels = mapper.poll()
        self.assertEqual(channels[6], 2000)
        self.assertEqual(channels[7], 1200)
        keyboard.bindings["arm"] = False
        mapper.poll()
        keyboard.bindings["arm"] = True
        self.assertEqual(mapper.poll()[6], 1000)

    def test_nav_wp_toggle(self) -> None:
        config = BridgeConfig(
            platform="fake",
            keyboard=keyboard_config("keyboard"),
        )
        keyboard = FakeKeyboard(backend="fake", bindings={"nav_wp": True})
        mapper = KeyboardMapper(config.keyboard, keyboard)
        self.assertEqual(mapper.poll()[5], 2000)
        keyboard.bindings["nav_wp"] = False
        mapper.poll()
        keyboard.bindings["nav_wp"] = True
        self.assertEqual(mapper.poll()[5], 1000)

    def test_pitch_direction(self) -> None:
        config = BridgeConfig(
            platform="fake",
            keyboard=keyboard_config("keyboard"),
        )
        config.keyboard.axis_rate = 1e9
        keyboard = FakeKeyboard(backend="fake", bindings={"pitch_up": True})
        mapper = KeyboardMapper(config.keyboard, keyboard)
        mapper.last -= 1.0
        self.assertEqual(mapper.poll()[1], 1000)
        keyboard.bindings["pitch_up"] = False
        keyboard.bindings["pitch_down"] = True
        mapper.last -= 1.0
        self.assertEqual(mapper.poll()[1], 2000)

    def test_restore_preserves_arm_mode_and_wp(self) -> None:
        config = BridgeConfig(
            platform="fake",
            keyboard=keyboard_config("keyboard"),
        )
        keyboard = FakeKeyboard(backend="fake")
        mapper = KeyboardMapper(config.keyboard, keyboard)
        last = [1500, 1500, 1200, 1500, 1500, 1000, 2000, 1600, 2000]
        mapper.restore_channels(last)
        channels = mapper.poll()
        self.assertEqual(channels[2], 1200)
        self.assertEqual(channels[5], 1000)
        self.assertEqual(channels[6], 2000)
        self.assertEqual(channels[7], 1600)


if __name__ == "__main__":
    unittest.main()
