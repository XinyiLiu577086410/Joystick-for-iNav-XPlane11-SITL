"""Logical keyboard actions.  Key names themselves stay platform-specific."""

from __future__ import annotations

KEYBOARD_ACTIONS = (
    "roll_left",
    "roll_right",
    "pitch_up",
    "pitch_down",
    "yaw_left",
    "yaw_right",
    "throttle_up",
    "throttle_down",
    "arm",
    "mode_1",
    "mode_2",
    "mode_3",
    "mode_4",
    "mode_5",
    "mode_6",
    "nav_wp",
)

KEYBOARD_ACTION_LABELS = {
    "roll_left": "横滚 左",
    "roll_right": "横滚 右",
    "pitch_up": "俯仰 上仰",
    "pitch_down": "俯仰 下俯",
    "yaw_left": "偏航 左",
    "yaw_right": "偏航 右",
    "throttle_up": "油门 增加",
    "throttle_down": "油门 减少",
    "arm": "解锁 / 上锁",
    "mode_1": "模式 1",
    "mode_2": "模式 2",
    "mode_3": "模式 3",
    "mode_4": "模式 4",
    "mode_5": "模式 5",
    "mode_6": "模式 6",
    "nav_wp": "NAV WP 开关（按一下切换）",
}
