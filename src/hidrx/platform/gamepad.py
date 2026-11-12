"""Cross-platform pygame gamepad backend used by the joystick setup wizard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from ..models import GamepadDevice

import os

os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")


class GamepadError(RuntimeError):
    pass


@dataclass
class PygameGamepad:
    name: str = ""
    num_axes: int = 0
    num_buttons: int = 0

    def __post_init__(self) -> None:
        try:
            import pygame
        except ImportError as exc:
            raise GamepadError("pygame is not installed: python -m pip install pygame") from exc
        self._pygame = pygame
        pygame.init()
        for _ in range(2):
            pygame.joystick.init()
            pygame.event.pump()
            pygame.event.get()
            if pygame.joystick.get_count() > 0:
                break
            pygame.joystick.quit()
        if pygame.joystick.get_count() == 0:
            raise GamepadError("no joystick/gamepad detected by SDL2")
        self._joy = pygame.joystick.Joystick(0)
        self._joy.init()
        self.name = self._joy.get_name()
        self.num_axes = self._joy.get_numaxes()
        self.num_buttons = self._joy.get_numbuttons()

    def snapshot(self) -> Tuple[List[float], List[int]]:
        try:
            self._pygame.event.pump()
            axes = [self._joy.get_axis(i) for i in range(self.num_axes)]
            buttons = [self._joy.get_button(i) for i in range(self.num_buttons)]
            return axes, buttons
        except Exception as exc:
            raise GamepadError(str(exc)) from exc

    def close(self) -> None:
        try:
            self._joy.quit()
            self._pygame.joystick.quit()
            self._pygame.quit()
        except Exception:
            pass
