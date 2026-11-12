"""Cross-platform pygame gamepad backend used by the gamepad setup wizard."""

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
        found = False
        for _ in range(2):
            pygame.joystick.init()
            pygame.event.pump()
            pygame.event.get()
            if pygame.joystick.get_count() > 0:
                found = True
                break
            pygame.joystick.quit()
        if not found:
            raise GamepadError("no gamepad detected by SDL2")
        self._joy = pygame.joystick.Joystick(0)
        self._joy.init()
        self.name = self._joy.get_name()
        self.num_axes = self._joy.get_numaxes()
        self.num_buttons = self._joy.get_numbuttons()

    def snapshot(self) -> Tuple[List[float], List[int]]:
        try:
            self._pygame.event.pump()
            if self._pygame.joystick.get_count() == 0 or not self._joy.get_init():
                raise GamepadError("gamepad removed")
            removed_event = getattr(self._pygame, "JOYDEVICEREMOVED", None)
            if removed_event is not None:
                for event in self._pygame.event.get():
                    if (
                        event.type == removed_event
                        and getattr(event, "instance_id", None) == self._joy.get_instance_id()
                    ):
                        raise GamepadError("gamepad removed")
            axes = [self._joy.get_axis(i) for i in range(self.num_axes)]
            buttons = [self._joy.get_button(i) for i in range(self.num_buttons)]
            return axes, buttons
        except GamepadError:
            raise
        except Exception as exc:
            raise GamepadError(str(exc)) from exc

    def close(self) -> None:
        try:
            self._joy.quit()
            self._pygame.joystick.quit()
            self._pygame.quit()
        except Exception:
            pass
