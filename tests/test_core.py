"""Core tests: MSP framing and channel mapping."""

from __future__ import annotations

import struct
import unittest

from hidrx.core.channels import AxisMap, ButtonMap, build_channels
from hidrx.core.config import BridgeConfig, config_from_dict
from hidrx.core.msp import msp_v1_frame, set_raw_rc_frame


class MspFrameTests(unittest.TestCase):
    def test_v1_frame(self) -> None:
        frame = msp_v1_frame(1, bytes((0, 2, 6)))
        self.assertEqual(frame[:3], b"$M<")
        self.assertEqual(frame[3], 3)
        self.assertEqual(frame[4], 1)
        self.assertEqual(frame[-1], 0 ^ 3 ^ 1 ^ 0 ^ 2 ^ 6)

    def test_set_raw_rc_roundtrip(self) -> None:
        channels = [1500] * 16
        frame = set_raw_rc_frame(channels)
        self.assertEqual(frame[3], 32)
        self.assertEqual(frame[4], 200)
        self.assertEqual(struct.unpack("<16H", frame[5:37]), tuple(channels))


class ChannelTests(unittest.TestCase):
    def test_bipolar_mid_endpoints_and_reverse(self) -> None:
        mapping = AxisMap(axis=0, channel=1)
        self.assertEqual(build_channels(BridgeConfig(axes=[mapping]), [0.0], [], {}, {})[0], 1500)
        self.assertEqual(build_channels(BridgeConfig(axes=[mapping]), [1.0], [], {}, {})[0], 2000)
        mapping.reverse = True
        self.assertEqual(build_channels(BridgeConfig(axes=[mapping]), [1.0], [], {}, {})[0], 1000)

    def test_multi_and_constants(self) -> None:
        mapping = AxisMap(
            axis=0,
            channel=8,
            kind="multi",
            levels=6,
            values=[1000, 1200, 1400, 1600, 1800, 2000],
        )
        config = BridgeConfig(axes=[mapping], constants={9: 2000})
        channels = build_channels(config, [1.0], [], {}, {})
        self.assertEqual(channels[7], 2000)
        self.assertEqual(channels[8], 2000)

    def test_button_toggle_and_switch(self) -> None:
        config = BridgeConfig(
            buttons=[ButtonMap(button=0, channel=7, toggle=True)],
            constants={9: 2000},
        )
        toggles: dict[int, bool] = {}
        previous: dict[int, bool] = {}
        self.assertEqual(build_channels(config, [], [0], toggles, previous)[6], 1000)
        self.assertEqual(build_channels(config, [], [1], toggles, previous)[6], 2000)
        self.assertEqual(build_channels(config, [], [1], toggles, previous)[6], 2000)

    def test_no_default_mapping(self) -> None:
        config = config_from_dict({"platform": "fake"})
        self.assertEqual(config.axes, [])
        self.assertEqual(config.keyboard.keys, {})


if __name__ == "__main__":
    unittest.main()
