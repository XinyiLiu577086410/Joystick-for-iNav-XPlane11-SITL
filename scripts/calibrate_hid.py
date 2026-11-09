#!/usr/bin/env python3
"""Interactive HID stick calibration for hid2msp.py.

Run:  python3 calibrate_hid.py
Move only the requested stick axis each step, then press Enter.
"""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

STEPS = [
    ("RIGHT_H", "右摇杆：只左右来回（Roll）"),
    ("RIGHT_V", "右摇杆：只上下来回（Pitch）"),
    ("LEFT_V",  "左摇杆：只上下来回（Throttle）"),
    ("LEFT_H",  "左摇杆：只左右来回（Yaw）"),
]


def sample(joy, seconds=1.4):
    axes_min = [999.0] * joy.get_numaxes()
    axes_max = [-999.0] * joy.get_numaxes()
    buttons = [0] * joy.get_numbuttons()
    end = time.time() + seconds
    while time.time() < end:
        pygame.event.pump()
        for i in range(joy.get_numaxes()):
            v = joy.get_axis(i)
            axes_min[i] = min(axes_min[i], v)
            axes_max[i] = max(axes_max[i], v)
        for i in range(joy.get_numbuttons()):
            buttons[i] = max(buttons[i], joy.get_button(i))
        time.sleep(0.02)
    return axes_min, axes_max, buttons


def main():
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("no joystick")
        return 1
    joy = pygame.joystick.Joystick(0)
    joy.init()
    print(f"device: {joy.get_name()}  axes={joy.get_numaxes()} buttons={joy.get_numbuttons()}")
    print("每次只动一个轴，动 1 秒左右，回中/回位后按 Enter。\n")

    result = {}
    for key, label in STEPS:
        input(f"{label}，然后按 Enter...")
        lo, hi, btns = sample(joy)
        changed = []
        for i, (a, b) in enumerate(zip(lo, hi)):
            if b - a > 0.25:
                changed.append({"axis": i, "min": round(a, 3), "max": round(b, 3)})
        result[key] = {"axes": changed, "buttons": [i for i, v in enumerate(btns) if v]}
        print("  变化轴:", changed if changed else "无")
        print("  按下的按钮:", result[key]["buttons"] or "无")
        print()

    print("=== 汇总 ===")
    for key, _ in STEPS:
        print(key, result[key])
    out = Path(__file__).resolve().parent.parent / "config" / "calibration.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n已写入 {out}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
