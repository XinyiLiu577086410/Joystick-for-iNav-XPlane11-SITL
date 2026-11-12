"""Bridge process entry point."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from ..core.bridge import BridgeRunner
from ..core.config import load_config
from ..core.keyboard import KeyboardMapper
from ..core.msp import MspLink
from ..core.startup import StartupError, require_ready
from ..platform.factory import create_platform
from ..platform.gamepad import PygameGamepad


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hidrx.bridge")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", choices=("auto", "joystick", "keyboard"), default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--rate", type=float, default=None)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.rate:
        config.rate_hz = args.rate

    platform = create_platform(Path.cwd())
    try:
        plan = require_ready(
            config,
            platform_id=platform.id,
            backend_id=platform.keyboard.backend,
            input_source=args.input,
        )
    except StartupError as exc:
        print(f"startup error: {exc}", file=sys.stderr)
        return 2

    link = MspLink(config.host, config.port)
    while not link.connect():
        print(f"waiting for SITL on {config.host}:{config.port}: {link.last_error}", file=sys.stderr)
        time.sleep(1.0)

    runner = BridgeRunner(
        link=link,
        config=config,
        input_source=plan.input_source,
        keyboard_backend=platform.keyboard,
        gamepad_factory=PygameGamepad,
        keyboard_factory=lambda: KeyboardMapper(config.keyboard, platform.keyboard),
        log=lambda message: print(message, flush=True),
    )
    try:
        return runner.run()
    except KeyboardInterrupt:
        return 0
    finally:
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
