"""Startup guard: reject missing, foreign or incomplete configurations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import (
    BridgeConfig,
    keyboard_complete,
    normalize_input_source,
    validate_config,
)
from ..constants import INPUT_AUTO, INPUT_KEYBOARD
from ..platform.base import KeyboardBackend


class StartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class StartupPlan:
    input_source: str
    keyboard_fallback: bool


def require_ready(
    config: BridgeConfig,
    platform_id: str,
    backend_id: str,
    input_source: Optional[str] = None,
    keyboard: Optional[KeyboardBackend] = None,
) -> StartupPlan:
    errors = validate_config(config, input_source)
    if config.platform and config.platform != platform_id:
        errors.append(
            f"config was created for platform {config.platform!r}; "
            f"current platform is {platform_id!r}; run setup again"
        )
    if config.keyboard.backend and config.keyboard.backend != backend_id:
        errors.append(
            f"keyboard.backend was created for {config.keyboard.backend!r}; "
            f"current backend is {backend_id!r}"
        )
    if keyboard is not None:
        for action, binding in config.keyboard.keys.items():
            try:
                keyboard.validate(binding)
            except ValueError as exc:
                errors.append(f"keyboard.{action}: {exc}")
    if errors:
        raise StartupError("; ".join(errors))

    source = normalize_input_source(input_source or config.keyboard.source)
    if source == INPUT_AUTO:
        fallback = config.keyboard.enabled and keyboard_complete(config.keyboard)
    elif source == INPUT_KEYBOARD:
        fallback = False
    else:
        fallback = False
    return StartupPlan(input_source=source, keyboard_fallback=fallback)
