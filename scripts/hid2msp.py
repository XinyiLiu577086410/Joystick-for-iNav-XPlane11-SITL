#!/usr/bin/env python3
"""
hid2msp.py (Windows) - HID gamepad -> INAV SITL MSP RX bridge

Sends MSP_SET_RAW_RC (200) frames over TCP to an INAV SITL UART that is
configured as MSP.  INAV then treats the gamepad exactly like an MSP receiver.
The macOS implementation lives on the main branch.

Typical SITL setup:
    inav_SITL --path=plane.bin --tcpbaseport=5760
    # UART1 = 5760 (Configurator), UART2 = 5761 (HITL plugin),
    # UART3 = 5762 (this bridge, set to MSP in Configurator/CLI)

Run:
    python hid2msp.py --list
    python hid2msp.py --port 5762
    python hid2msp.py --port 5762 --test
    python hid2msp.py --port 5762 --once
    python hid2msp.py --keys

Input is selected by config/keyboard.source:
  auto      = gamepad if present, otherwise keyboard
  hid       = force gamepad
  keyboard  = force keyboard

pygame is only needed for gamepad mode; keyboard mode uses GetAsyncKeyState.
If a local ``.deps`` folder exists next to the repository, it is added to
``sys.path`` so pygame can live there without a global install.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from keyboard_input import (
    KeyboardConfig,
    KeyboardInput,
    monitor_keyboard,
)

_LOCAL_DEPS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".deps")
if os.path.isdir(_LOCAL_DEPS) and _LOCAL_DEPS not in sys.path:
    sys.path.insert(0, _LOCAL_DEPS)

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

MSP_SET_RAW_RC = 200
CHANNEL_COUNT = 16
PWM_MIN, PWM_MID, PWM_MAX = 1000, 1500, 2000


# ---------------------------------------------------------------------------
# MSP v1
# ---------------------------------------------------------------------------
def msp_v1_frame(command: int, payload: bytes = b"") -> bytes:
    body = bytes((len(payload), command)) + payload
    checksum = 0
    for byte in body:
        checksum ^= byte
    return b"$M<" + body + bytes((checksum,))


class MspLink:
    """Minimal MSP v1 client over TCP.  Only TX is needed for raw RC."""

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.last_error: Optional[str] = None

    def connect(self) -> bool:
        self.close()
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock.settimeout(self.timeout)
            self.last_error = None
            return True
        except OSError as exc:
            self.last_error = str(exc)
            self.sock = None
            return False

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def send_raw_rc(self, channels: Sequence[int]) -> bool:
        if self.sock is None:
            return False
        payload = struct.pack("<%dH" % len(channels), *channels)
        try:
            self.sock.sendall(msp_v1_frame(MSP_SET_RAW_RC, payload))
            return True
        except OSError as exc:
            self.last_error = str(exc)
            self.close()
            return False


# ---------------------------------------------------------------------------
# Channel mapping
# ---------------------------------------------------------------------------
@dataclass
class AxisMap:
    axis: int
    channel: int
    kind: str = "bipolar"          # bipolar/unipolar/tri/binary/multi
    reverse: bool = False
    trim: int = PWM_MID            # center for bipolar, low endpoint for unipolar
    deadband: float = 0.06
    expo: float = 0.0
    threshold: float = 0.0         # tri/binary switch center or threshold
    levels: int = 6                # multi: number of discrete positions
    values: List[int] = field(default_factory=list)  # multi: PWM values per position


@dataclass
class ButtonMap:
    button: int
    channel: int
    low: int = PWM_MIN
    high: int = PWM_MAX
    toggle: bool = True


@dataclass
class Button3Map:
    """Three-position switch made from two buttons: up=high, down=low, neither=mid."""
    channel: int
    up: int = -1
    down: int = -1
    low: int = PWM_MIN
    mid: int = PWM_MID
    high: int = PWM_MAX


@dataclass
class CombineMap:
    """Derive a channel from two switch channels (e.g. 3-position SWA + 2-position SWC)."""
    channel: int
    a: int
    b: int
    a_levels: int = 3
    b_levels: int = 2
    values: List[int] = field(default_factory=lambda: [1000, 1200, 1400, 1600, 1800, 2000])


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 5762
    rate_hz: float = 50.0
    axes: List[AxisMap] = field(default_factory=list)
    buttons: List[ButtonMap] = field(default_factory=list)
    buttons3: List[Button3Map] = field(default_factory=list)
    combine: List[CombineMap] = field(default_factory=list)
    constants: Dict[int, int] = field(default_factory=dict)
    keyboard: KeyboardConfig = field(default_factory=KeyboardConfig)


def default_config() -> Config:
    # No built-in HID/keyboard mapping: run `hidctl setup` / `setup keyboard`
    # once to generate config/hid2msp_inav.json for this machine.
    return Config()


def load_config(path: Optional[str]) -> Config:
    cfg = default_config()
    if not path:
        return cfg
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    cfg.host = data.get("host", cfg.host)
    cfg.port = int(data.get("port", cfg.port))
    cfg.rate_hz = float(data.get("rate_hz", cfg.rate_hz))
    if "axes" in data:
        cfg.axes = [AxisMap(**item) for item in data["axes"]]
    if "buttons" in data:
        cfg.buttons = [ButtonMap(**item) for item in data["buttons"]]
    if "buttons3" in data:
        cfg.buttons3 = [Button3Map(**item) for item in data["buttons3"]]
    if "combine" in data:
        cfg.combine = [CombineMap(**item) for item in data["combine"]]
    if "constants" in data:
        cfg.constants = {int(k): int(v) for k, v in data["constants"].items()}
    if "keyboard" in data:
        raw = data.get("keyboard") or {}
        if not isinstance(raw, dict):
            raise ValueError("keyboard must be an object")
        source = str(raw.get("source", "auto")).lower()
        if source not in ("auto", "hid", "keyboard"):
            raise ValueError("keyboard.source must be auto, hid, or keyboard")
        keys = {}
        raw_keys = raw.get("keys") or {}
        if not isinstance(raw_keys, dict):
            raise ValueError("keyboard.keys must be an object")
        keys.update({str(k): str(v) for k, v in raw_keys.items()})
        cfg.keyboard = KeyboardConfig(
            enabled=bool(raw.get("enabled", True)),
            source=source,
            axis_rate=float(raw.get("axis_rate", 600.0)),
            throttle_rate=float(raw.get("throttle_rate", 600.0)),
            keys=keys,
            foreground_only=bool(raw.get("foreground_only", True)),
            window_process=str(raw.get("window_process", "X-Plane.exe")),
        )
    return cfg


def clamp_pwm(value: float) -> int:
    return int(max(PWM_MIN, min(PWM_MAX, round(value))))


def apply_deadband(value: float, deadband: float) -> float:
    if abs(value) <= deadband:
        return 0.0
    return math.copysign((abs(value) - deadband) / (1.0 - deadband), value)


def apply_expo(value: float, expo: float) -> float:
    # expo in [0, 1); positive expo softens the center.
    return (1.0 - expo) * value + expo * value * value * value


def axis_to_pwm(raw: float, mapping: AxisMap) -> int:
    value = -raw if mapping.reverse else raw
    value = max(-1.0, min(1.0, value))
    if mapping.kind == "unipolar":
        value = max(0.0, value)
        return clamp_pwm(mapping.trim + value * (PWM_MAX - mapping.trim))
    if mapping.kind == "tri":
        if value < mapping.threshold - 0.33:
            return PWM_MIN
        if value < mapping.threshold + 0.33:
            return PWM_MID
        return PWM_MAX
    if mapping.kind == "binary":
        return PWM_MAX if value >= mapping.threshold else PWM_MIN
    if mapping.kind == "multi":
        n = max(2, mapping.levels)
        idx = int(round((value + 1.0) * (n - 1) / 2.0))
        idx = max(0, min(n - 1, idx))
        if mapping.values and len(mapping.values) >= n:
            return clamp_pwm(mapping.values[idx])
        return clamp_pwm(PWM_MIN + idx * (PWM_MAX - PWM_MIN) / (n - 1))
    value = apply_deadband(value, mapping.deadband)
    value = apply_expo(value, mapping.expo)
    return clamp_pwm(mapping.trim + value * 500.0)


# ---------------------------------------------------------------------------
# Gamepad
# ---------------------------------------------------------------------------
class Gamepad:
    def __init__(self) -> None:
        import pygame  # lazy import so --test works without pygame
        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            raise RuntimeError("No joystick/gamepad detected by SDL2")
        self.pygame = pygame
        self.joy = pygame.joystick.Joystick(0)
        self.joy.init()
        self.name = self.joy.get_name()
        self.num_axes = self.joy.get_numaxes()
        self.num_buttons = self.joy.get_numbuttons()

    def poll(self) -> Tuple[List[float], List[int]]:
        self.pygame.event.pump()
        axes = [self.joy.get_axis(i) for i in range(self.num_axes)]
        buttons = [self.joy.get_button(i) for i in range(self.num_buttons)]
        return axes, buttons

    def close(self) -> None:
        try:
            self.joy.quit()
            self.pygame.joystick.quit()
            self.pygame.quit()
        except Exception:
            pass


def list_gamepads() -> int:
    try:
        import pygame
    except ImportError:
        print("pygame is not installed.  Install it with:  python3 -m pip install pygame", file=sys.stderr)
        return 1
    pygame.init()
    pygame.joystick.init()
    count = pygame.joystick.get_count()
    print("joysticks:", count)
    for index in range(count):
        joy = pygame.joystick.Joystick(index)
        joy.init()
        print(f"  [{index}] {joy.get_name()}  axes={joy.get_numaxes()} buttons={joy.get_numbuttons()}")
    if count:
        joy = pygame.joystick.Joystick(0)
        joy.init()
        print("\nMove sticks/triggers; Ctrl-C to stop.")
        try:
            while True:
                pygame.event.pump()
                axes = [round(joy.get_axis(i), 3) for i in range(joy.get_numaxes())]
                buttons = [joy.get_button(i) for i in range(joy.get_numbuttons())]
                print("\raxes=" + str(axes) + " buttons=" + str(buttons), end="", flush=True)
                time.sleep(0.05)
        except KeyboardInterrupt:
            print()
    pygame.quit()
    return 0


def pwm_to_level(value: int, levels: int) -> int:
    if levels <= 1:
        return 0
    if levels == 2:
        return 1 if value >= PWM_MID else 0
    if levels == 3:
        if value < 1250:
            return 0
        if value < 1750:
            return 1
        return 2
    # generic evenly-spaced levels
    span = (PWM_MAX - PWM_MIN) / max(1, levels - 1)
    return max(0, min(levels - 1, int(round((value - PWM_MIN) / span))))


def build_channels(cfg: Config, axes: Sequence[float], buttons: Sequence[int],
                   toggles: Dict[int, bool], previous: Dict[int, bool]) -> List[int]:
    channels = [PWM_MID] * CHANNEL_COUNT
    channels[2] = PWM_MIN  # throttle low by default
    for mapping in cfg.axes:
        if mapping.axis < len(axes):
            channels[mapping.channel - 1] = axis_to_pwm(axes[mapping.axis], mapping)
    for mapping in cfg.buttons:
        if mapping.button >= len(buttons):
            continue
        pressed = bool(buttons[mapping.button])
        was_pressed = previous.get(mapping.button, False)
        if mapping.toggle:
            if pressed and not was_pressed:
                toggles[mapping.button] = not toggles.get(mapping.button, False)
            channels[mapping.channel - 1] = mapping.high if toggles.get(mapping.button, False) else mapping.low
        else:
            channels[mapping.channel - 1] = mapping.high if pressed else mapping.low
        previous[mapping.button] = pressed
    for mapping in cfg.buttons3:
        up = 0 <= mapping.up < len(buttons) and bool(buttons[mapping.up])
        down = 0 <= mapping.down < len(buttons) and bool(buttons[mapping.down])
        channels[mapping.channel - 1] = mapping.high if up else (mapping.low if down else mapping.mid)
    for mapping in cfg.combine:
        a_value = channels[mapping.a - 1]
        b_value = channels[mapping.b - 1]
        a_level = pwm_to_level(a_value, mapping.a_levels)
        b_level = pwm_to_level(b_value, mapping.b_levels)
        index = a_level * mapping.b_levels + b_level
        if 0 <= index < len(mapping.values):
            channels[mapping.channel - 1] = mapping.values[index]
    for channel, value in cfg.constants.items():
        if 1 <= channel <= CHANNEL_COUNT:
            channels[channel - 1] = value
    return channels


def synthetic_channels(t: float) -> List[int]:
    channels = [PWM_MID] * CHANNEL_COUNT
    channels[0] = clamp_pwm(PWM_MID + 400 * math.sin(t * 0.7))       # roll
    channels[1] = clamp_pwm(PWM_MID + 300 * math.sin(t * 0.5))       # pitch
    channels[2] = clamp_pwm(PWM_MID + 400 * math.sin(t * 0.3))       # throttle
    channels[3] = clamp_pwm(PWM_MID + 400 * math.sin(t * 0.9))       # yaw
    channels[4] = PWM_MIN                                            # disarmed
    return channels


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(cfg: Config, test: bool, once: bool, verbose: bool) -> int:
    link = MspLink(cfg.host, cfg.port)
    if not link.connect():
        if once:
            print(f"cannot connect to {cfg.host}:{cfg.port}: {link.last_error}", file=sys.stderr)
            return 2
        print(
            f"cannot connect to {cfg.host}:{cfg.port}: {link.last_error}; "
            "retrying (Ctrl-C to stop)",
            file=sys.stderr,
            flush=True,
        )
        while not link.connect():
            time.sleep(1.0)
        print(f"connected to {cfg.host}:{cfg.port}", flush=True)

    gamepad: Optional[Gamepad] = None
    keyboard: Optional[KeyboardInput] = None
    if not test:
        source = cfg.keyboard.source if cfg.keyboard.enabled else "hid"
        if source == "auto":
            try:
                gamepad = Gamepad()
                print(f"gamepad: {gamepad.name}  axes={gamepad.num_axes} buttons={gamepad.num_buttons}")
            except Exception as gamepad_error:
                try:
                    keyboard = KeyboardInput(cfg.keyboard)
                    print("keyboard: enabled (no gamepad detected)")
                except Exception as keyboard_error:
                    print(f"gamepad error: {gamepad_error}", file=sys.stderr)
                    print(f"keyboard error: {keyboard_error}", file=sys.stderr)
                    link.close()
                    return 2
        elif source == "keyboard":
            try:
                keyboard = KeyboardInput(cfg.keyboard)
                print("keyboard: enabled")
            except Exception as exc:
                print(f"keyboard error: {exc}", file=sys.stderr)
                link.close()
                return 2
        elif source == "hid":
            try:
                gamepad = Gamepad()
                print(f"gamepad: {gamepad.name}  axes={gamepad.num_axes} buttons={gamepad.num_buttons}")
            except Exception as exc:
                print(f"gamepad error: {exc}", file=sys.stderr)
                link.close()
                return 2
        else:
            print(f"invalid keyboard source: {source}", file=sys.stderr)
            link.close()
            return 2

    if gamepad is not None and not (cfg.axes or cfg.buttons or cfg.buttons3 or cfg.combine):
        print(
            "no HID mapping configured; run: .\\hidctl.cmd setup",
            file=sys.stderr,
        )
        link.close()
        return 2

    period = 1.0 / max(1.0, cfg.rate_hz)
    toggles: Dict[int, bool] = {}
    previous_buttons: Dict[int, bool] = {}
    next_tx = time.monotonic()
    next_log = next_tx + 1.0
    started = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            if test:
                channels = synthetic_channels(now - started)
            elif gamepad is not None:
                axes, buttons = gamepad.poll()
                channels = build_channels(cfg, axes, buttons, toggles, previous_buttons)
            elif keyboard is not None:
                channels = keyboard.poll()
            else:
                print("no input source active", file=sys.stderr)
                return 2

            if not link.send_raw_rc(channels):
                print(f"send failed: {link.last_error}; reconnecting...", file=sys.stderr)
                time.sleep(0.5)
                if not link.connect():
                    print(f"reconnect failed: {link.last_error}", file=sys.stderr)
                    time.sleep(0.5)
                    continue

            if verbose and now >= next_log:
                print("ch=" + " ".join(str(v) for v in channels[:8]))
                next_log = now + 1.0
            if once:
                return 0

            next_tx += period
            sleep_for = next_tx - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tx = time.monotonic()
    except KeyboardInterrupt:
        return 0
    finally:
        link.close()
        if gamepad is not None:
            gamepad.close()
        if keyboard is not None:
            keyboard.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HID gamepad -> INAV SITL MSP RX bridge")
    parser.add_argument("--host", default=None, help="SITL host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="SITL TCP port for the MSP UART (default 5762)")
    parser.add_argument("--config", help="JSON mapping file")
    parser.add_argument("--rate", type=float, default=None, help="RC frame rate in Hz (default 50)")
    parser.add_argument("--list", action="store_true", help="list gamepads and live axes/buttons")
    parser.add_argument("--keys", action="store_true", help="list keyboard-derived channels (no gamepad)")
    parser.add_argument("--source", choices=("auto", "hid", "keyboard"), default=None, help="override keyboard.source")
    parser.add_argument("--test", action="store_true", help="send synthetic channel sweeps (no gamepad)")
    parser.add_argument("--once", action="store_true", help="send one frame and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="print channels once per second")
    args = parser.parse_args(argv)

    if args.list:
        return list_gamepads()

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port
    if args.rate:
        cfg.rate_hz = args.rate
    if args.source:
        cfg.keyboard.enabled = True
        cfg.keyboard.source = args.source
    if args.keys:
        return monitor_keyboard(cfg.keyboard)

    return run(cfg, test=args.test, once=args.once, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
