#!/usr/bin/env python3
"""Interactive keyboard-map wizard for hid2msp.

Usage:
    python3 scripts/keymap_wizard.py
    python3 scripts/keymap_wizard.py --manual
    python3 scripts/keymap_wizard.py --apply

Normal mode reads physical keys through CoreGraphics.  If Input Monitoring is
not granted, use --manual and type macOS key names instead.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
CONFIG = ROOT / "config" / "hid2msp_inav.json"
HIDCTL = ROOT / "hidctl"

sys.path.insert(0, str(SCRIPT_DIR))
from keyboard_input import (  # noqa: E402
    DEFAULT_KEYS,
    input_monitoring_trusted,
    key_name_for_code,
    read_pressed_keycodes,
    resolve_keycode,
)

ACTIONS = [
    ("roll_left", "Roll 左"),
    ("roll_right", "Roll 右"),
    ("pitch_up", "Pitch 上"),
    ("pitch_down", "Pitch 下"),
    ("yaw_left", "Yaw 左"),
    ("yaw_right", "Yaw 右"),
    ("arm", "解锁/上锁切换"),
    ("throttle_up", "增加油门"),
    ("throttle_down", "减少油门"),
    ("mode_1", "模式 1 ANGLE"),
    ("mode_2", "模式 2 HORIZON"),
    ("mode_3", "模式 3 MANUAL"),
    ("mode_4", "模式 4 NAV CRUISE"),
    ("mode_5", "模式 5 NAV POSHOLD"),
    ("mode_6", "模式 6 NAV RTH"),
]


def load_json() -> dict:
    if not CONFIG.is_file():
        raise SystemExit(f"config not found: {CONFIG}")
    return json.loads(CONFIG.read_text())


def current_keys(data: dict) -> dict[str, str]:
    keys = dict(DEFAULT_KEYS)
    raw = (data.get("keyboard") or {}).get("keys") or {}
    keys.update({str(k): str(v) for k, v in raw.items()})
    return keys


def print_summary(keys: dict[str, str]) -> None:
    print("\n当前键位：")
    for action, label in ACTIONS:
        print(f"  {action:14} {keys.get(action, '?'):16} {label}")


def manual_mode(keys: dict[str, str]) -> dict[str, str] | None:
    print("\n手动键名模式。直接输入键名，回车保留，输入 skip 跳过，输入 q 退出。")
    print("键名示例：a, w, 1, space, left_shift, left_control, left_option, fn\n")
    used = {key: action for action, key in keys.items()}
    result = dict(keys)

    for action, label in ACTIONS:
        while True:
            current = result.get(action, "?")
            try:
                value = input(f"{label} [{action}] 当前 {current}: ").strip()
            except EOFError:
                print("\nstdin 结束，取消。")
                return None
            if not value:
                break
            if value.lower() == "q":
                return None
            if value.lower() == "skip":
                break
            try:
                resolve_keycode(value)
            except ValueError as exc:
                print(f"  {exc}")
                continue
            owner = used.get(value.lower())
            if owner and owner != action:
                print(f"  键 {value!r} 已被 {owner} 使用，请换一个。")
                continue
            old = result.get(action)
            if old:
                used.pop(old.lower(), None)
            result[action] = value.lower()
            used[value.lower()] = action
            break
    return result


def wait_release() -> None:
    while read_pressed_keycodes():
        time.sleep(0.05)


def capture_one(timeout: float = 20.0) -> tuple[str, str | None]:
    """Return (status, keyname); status is keep/skip/key/timeout."""
    wait_release()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pressed = read_pressed_keycodes()
        if not pressed:
            time.sleep(0.03)
            continue
        code = sorted(pressed)[0]
        if code == 36:  # Return
            return "keep", None
        if code == 53:  # Escape
            return "skip", None
        name = key_name_for_code(code)
        wait_release()
        if name is None:
            print(f"  未识别的键码 {code}，请换一个。")
            return "unknown", None
        return "key", name
    return "timeout", None


def capture_mode(keys: dict[str, str]) -> dict[str, str] | None:
    trusted = input_monitoring_trusted()
    if trusted is not True:
        print("\nInput Monitoring 未授权，无法读取物理按键。")
        print("请给 Python/Terminal 授权后重跑，或使用：")
        print("  ./hidctl keys --manual")
        return None

    print("\n按键模式：按目标键；Enter 保留当前，Esc 跳过，20 秒超时保留。")
    print("每个动作只按一个键，按完松开。\n")
    used = {key: action for action, key in keys.items()}
    result = dict(keys)

    for action, label in ACTIONS:
        while True:
            print(f"{label} [{action}] 当前 {result.get(action, '?')} ... ", end="", flush=True)
            status, name = capture_one()
            if status == "keep":
                print("保留")
                break
            if status == "skip":
                print("跳过")
                break
            if status == "timeout":
                print("超时，保留")
                break
            if status == "unknown":
                continue
            assert name is not None
            owner = used.get(name)
            if owner and owner != action:
                print(f"键 {name!r} 已被 {owner} 使用，请换一个。")
                continue
            old = result.get(action)
            if old:
                used.pop(old.lower(), None)
            result[action] = name
            used[name] = action
            print(name)
            break
    return result


def save(data: dict, keys: dict[str, str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = CONFIG.with_name(f"{CONFIG.name}.bak-{stamp}")
    shutil.copy2(CONFIG, backup)

    keyboard = data.setdefault("keyboard", {})
    keyboard["keys"] = {action: keys[action] for action, _ in ACTIONS}
    CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return backup


def validate() -> bool:
    result = subprocess.run(
        [str(HIDCTL), "config", "check"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive keyboard-map wizard")
    parser.add_argument("--manual", action="store_true", help="type key names instead of pressing keys")
    parser.add_argument("--apply", action="store_true", help="restart bridge after saving")
    args = parser.parse_args(argv)

    data = load_json()
    keys = current_keys(data)
    print_summary(keys)

    result = manual_mode(keys) if args.manual else capture_mode(keys)
    if result is None:
        print("\n未修改配置。")
        return 0

    print_summary(result)
    try:
        answer = input("\n保存到 config/hid2msp_inav.json? [Y/n] ").strip().lower()
    except EOFError:
        answer = "n"
    if answer and answer not in ("y", "yes"):
        print("未保存。")
        return 0

    backup = save(data, result)
    if not validate():
        shutil.copy2(backup, CONFIG)
        print(f"校验失败，已恢复备份：{backup}")
        return 1

    print(f"已保存；备份：{backup}")
    should_apply = args.apply
    if not should_apply:
        try:
            should_apply = input("重启 bridge 使配置生效? [Y/n] ").strip().lower() in ("", "y", "yes")
        except EOFError:
            should_apply = False
    if should_apply:
        return subprocess.run([str(HIDCTL), "restart", "bridge"]).returncode
    print("稍后执行：./hidctl restart bridge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
