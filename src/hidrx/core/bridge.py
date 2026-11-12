"""Bridge runtime: gamepad primary, optional keyboard fallback, no exit on loss."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..constants import INPUT_AUTO, INPUT_KEYBOARD
from ..models import GamepadDevice
from ..platform.base import KeyboardBackend
from .channels import build_channels
from .config import BridgeConfig, keyboard_complete, normalize_input_source
from .keyboard import KeyboardMapper
from .msp import MspLink


class BridgeError(RuntimeError):
    pass


@dataclass
class BridgeRunner:
    link: MspLink
    config: BridgeConfig
    input_source: str
    keyboard_backend: KeyboardBackend
    gamepad_factory: Callable[[], GamepadDevice]
    keyboard_factory: Callable[[], KeyboardMapper]
    period: float = 0.02
    reconnect_interval: float = 2.0
    log: Callable[[str], None] = lambda message: None

    gamepad: Optional[GamepadDevice] = None
    keyboard: Optional[KeyboardMapper] = None
    waiting: bool = False
    last_channels: Optional[List[int]] = None
    toggles: Dict[int, bool] = field(default_factory=dict)
    previous_buttons: Dict[int, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.input_source = normalize_input_source(self.input_source)
        self.period = 1.0 / max(1.0, self.config.rate_hz)

    @property
    def fallback_available(self) -> bool:
        return self.input_source == INPUT_AUTO and keyboard_complete(self.config.keyboard) and self.config.keyboard.enabled

    def _open_gamepad(self) -> bool:
        try:
            self.gamepad = self.gamepad_factory()
            self.toggles.clear()
            self.previous_buttons.clear()
            self.log("gamepad connected")
            return True
        except Exception as exc:
            self.gamepad = None
            self.log(f"gamepad unavailable: {exc}")
            return False

    def _open_keyboard(self) -> bool:
        try:
            self.keyboard = self.keyboard_factory()
            if self.last_channels is not None:
                self.keyboard.restore_channels(self.last_channels)
            self.log("keyboard enabled")
            return True
        except Exception as exc:
            self.keyboard = None
            self.log(f"keyboard unavailable: {exc}")
            return False

    def _enter_waiting(self) -> None:
        self.waiting = True
        self.log("RC paused; waiting for gamepad (SITL should failsafe)")

    def start(self) -> None:
        if self.input_source == INPUT_KEYBOARD:
            if not self._open_keyboard():
                raise BridgeError("keyboard input requested but not configured")
            return
        if self._open_gamepad():
            return
        if self.fallback_available and self._open_keyboard():
            return
        self._enter_waiting()

    def run(self, max_frames: Optional[int] = None) -> int:
        self.start()
        frames = 0
        next_probe = time.monotonic() + self.reconnect_interval
        while max_frames is None or frames < max_frames:
            now = time.monotonic()
            channels: Optional[List[int]] = None

            if self.gamepad is not None:
                try:
                    axes, buttons = self.gamepad.snapshot()
                    channels = build_channels(
                        self.config, axes, buttons, self.toggles, self.previous_buttons
                    )
                except Exception as exc:
                    self.log(f"gamepad lost: {exc}")
                    try:
                        self.gamepad.close()
                    except Exception:
                        pass
                    self.gamepad = None
                    next_probe = now + self.reconnect_interval
                    if self.fallback_available and self._open_keyboard():
                        channels = None
                    else:
                        self._enter_waiting()
            elif self.keyboard is not None:
                channels = self.keyboard.poll()
                if self.fallback_available and now >= next_probe:
                    next_probe = now + self.reconnect_interval
                    if self._open_gamepad():
                        try:
                            self.keyboard.close()
                        except Exception:
                            pass
                        self.keyboard = None
                        channels = None
            else:
                if now >= next_probe:
                    next_probe = now + self.reconnect_interval
                    if self._open_gamepad():
                        continue
                time.sleep(min(0.2, self.period))
                continue

            if channels is not None:
                self.last_channels = channels
                if not self.link.send_raw_rc(channels):
                    self.log(f"send failed: {self.link.last_error}")
                    self.link.connect()
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    break

            sleep_for = next_wake(now, self.period)
            if sleep_for > 0:
                time.sleep(sleep_for)
        return 0

    def close(self) -> None:
        if self.gamepad is not None:
            try:
                self.gamepad.close()
            except Exception:
                pass
        if self.keyboard is not None:
            try:
                self.keyboard.close()
            except Exception:
                pass
        self.link.close()


def next_wake(now: float, period: float) -> float:
    return max(0.0, period - (time.monotonic() - now))
