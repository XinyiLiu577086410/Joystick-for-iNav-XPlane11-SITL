"""Shared constants for RC channels and bridge modes."""

from __future__ import annotations

PWM_MIN = 1000
PWM_MID = 1500
PWM_MAX = 2000

CHANNEL_COUNT = 16

MSP_SET_RAW_RC = 200

MODE_VALUES = (1000, 1200, 1400, 1600, 1800, 2000)

INPUT_AUTO = "auto"
INPUT_JOYSTICK = "joystick"
INPUT_KEYBOARD = "keyboard"
INPUT_MODES = (INPUT_AUTO, INPUT_JOYSTICK, INPUT_KEYBOARD)
