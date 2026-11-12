"""Cross-platform CLI: INAV selection, config checks and SITL/bridge control."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ..core.config import ConfigError
from ..core.startup import StartupError
from ..models import ProcessHandle
from ..platform.factory import create_platform
from ..services.bridge import BridgeService
from ..services.config import ConfigService
from ..services.inav import InavError, InavService
from ..services.runtime import RuntimeStore
from ..services.setup import KeyboardSetupService, SetupError
from ..services.sitl import SitlError, SitlService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hidrx", description="INAV SITL bridge and lifecycle manager")
    sub = parser.add_subparsers(dest="command", required=True)

    inav = sub.add_parser("inav", help="inspect and select INAV SITL versions")
    inav_sub = inav.add_subparsers(dest="inav_command", required=True)
    inav_sub.add_parser("list", help="list installed INAV SITL versions")
    use = inav_sub.add_parser("use", help="set the active INAV version")
    use.add_argument("version")
    check = inav_sub.add_parser("check", help="probe an INAV SITL path or directory")
    check.add_argument("path", type=Path)

    config = sub.add_parser("config", help="configuration checks")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("check", help="load and validate hid2msp_inav.json")

    setup = sub.add_parser("setup", help="interactive setup (no defaults)")
    setup_sub = setup.add_subparsers(dest="setup_command", required=True)
    setup_sub.add_parser("keyboard", help="capture every keyboard action")
    setup_sub.add_parser("joystick", help="detect sticks, mode knob and arm button")

    for name in ("start", "stop"):
        command = sub.add_parser(name)
        command.add_argument("component", nargs="?", default="all", choices=("all", "sitl", "bridge"))
        if name == "start":
            command.add_argument("--input", choices=("auto", "joystick", "keyboard"), default=None)
            command.add_argument("--inav-version", default=None)
            command.add_argument("--inav-path", type=Path, default=None)

    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    sub.add_parser("doctor")
    return parser


class Context:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.platform = create_platform(repo_root)
        self.paths = self.platform.paths
        self.store = RuntimeStore(self.paths.run_dir)
        self.inav = InavService(
            locator=self.platform.inav,
            config_dir=self.paths.config_dir,
            runtime_dir=self.paths.runtime_dir,
            platform_id=self.platform.id,
        )
        self.config = ConfigService(
            self.paths.config_dir / "hid2msp_inav.json",
            platform_id=self.platform.id,
            keyboard_backend=self.platform.keyboard.backend,
        )
        self.sitl = SitlService(self.platform.process, self.paths, self.inav)
        self.bridge = BridgeService(
            self.platform.process,
            self.paths,
        )


def _alive(context: Context, component: str) -> Optional[ProcessHandle]:
    handle = context.store.load(component)
    if handle is not None and context.platform.process.is_alive(handle):
        return handle
    if handle is not None:
        context.store.remove(component)
    return None


def cmd_inav(context: Context, args: argparse.Namespace) -> int:
    if args.inav_command == "list":
        installs = context.inav.list()
        if not installs:
            print("no INAV SITL installation found")
            return 0
        print(f"{'VERSION':10} {'BUILD':10} PATH")
        for install in installs:
            print(f"{install.version:10} {install.build or '-':10} {install.path}")
        return 0
    if args.inav_command == "use":
        selection = context.inav.resolve(version=args.version)
        context.inav.use(selection.install)
        print(f"active INAV: {selection.install.version}  {selection.install.path}")
        return 0
    if args.inav_command == "check":
        install = context.platform.inav.resolve_path(args.path)
        if install is None:
            print(f"no INAV SITL found at {args.path}", file=sys.stderr)
            return 1
        print(f"{install.version}  {install.build or '-'}  {install.path}")
        return 0
    return 1


def cmd_config(context: Context, args: argparse.Namespace) -> int:
    config = context.config.load()
    errors = []
    try:
        context.config.plan(config)
    except StartupError as exc:
        errors.append(str(exc))
    if errors:
        for item in errors:
            print(f"ERROR {item}", file=sys.stderr)
        return 1
    print(f"OK: {context.config.config_path}")
    return 0


def cmd_setup(context: Context, args: argparse.Namespace) -> int:
    if args.setup_command == "keyboard":
        service = KeyboardSetupService(
            keyboard=context.platform.keyboard,
            config_path=context.config.config_path,
            platform_id=context.platform.id,
        )

        def prompt(action: str) -> None:
            print(f"\n{action}: press a key or combination (30s timeout)...")

        try:
            keys = service.capture_all(
                lambda action: context.platform.keyboard.capture(30.0),
                prompt=prompt,
            )
            service.save(keys)
        except (SetupError, ValueError, KeyboardInterrupt) as exc:
            print(f"setup failed: {exc}", file=sys.stderr)
            return 1
        print(f"keyboard: saved {len(keys)} bindings to {context.config.config_path}")
        return 0

    if args.setup_command == "joystick":
        from ..platform.gamepad import GamepadError, PygameGamepad
        from ..services.joystick_setup import JoystickSetupService

        service = JoystickSetupService(
            config_path=context.config.config_path,
            platform_id=context.platform.id,
            keyboard_backend=context.platform.keyboard.backend,
        )
        device = None
        try:
            device = PygameGamepad()
            print(f"gamepad: {device.name} axes={device.num_axes} buttons={device.num_buttons}")
            config = service.capture(device, prompt=lambda text: print(f"\n{text}"))
            service.save(config)
        except (GamepadError, SetupError, KeyboardInterrupt) as exc:
            print(f"setup failed: {exc}", file=sys.stderr)
            return 1
        finally:
            if device is not None:
                device.close()
        print(f"joystick: saved {len(config.axes)} axes/{len(config.buttons)} buttons")
        return 0

    print(f"unsupported setup: {args.setup_command}", file=sys.stderr)
    return 1


def cmd_start(context: Context, args: argparse.Namespace) -> int:
    config = context.config.load()
    plan = context.config.plan(config, args.input)
    selection = context.inav.resolve(args.inav_version, args.inav_path)

    started = []
    try:
        if args.component in ("all", "sitl"):
            handle = context.sitl.start(selection)
            context.store.save("sitl", handle)
            started.append("sitl")
            print(f"sitl: started pid={handle.pid}")
        if args.component in ("all", "bridge"):
            handle = context.bridge.start(context.config.config_path, plan.input_source)
            context.store.save("bridge", handle)
            started.append("bridge")
            print(f"bridge: started pid={handle.pid} input={plan.input_source}")
    except (SitlError, OSError) as exc:
        print(f"start failed: {exc}", file=sys.stderr)
        for component in reversed(started):
            handle = _alive(context, component)
            if handle is not None:
                context.platform.process.stop(handle)
                context.store.remove(component)
        return 1
    print(f"inav: {selection.install.version} ({selection.source})")
    return 0


def cmd_stop(context: Context, args: argparse.Namespace) -> int:
    components = ["bridge", "sitl"] if args.component == "all" else [args.component]
    for component in components:
        handle = context.store.load(component)
        if handle is None:
            print(f"{component}: not running")
            continue
        if context.platform.process.is_alive(handle):
            context.platform.process.stop(handle)
            print(f"{component}: stopped pid={handle.pid}")
        else:
            print(f"{component}: not running")
        context.store.remove(component)
    return 0


def cmd_status(context: Context, args: argparse.Namespace) -> int:
    data = {"platform": context.platform.id, "components": {}}
    for component in ("sitl", "bridge"):
        handle = context.store.load(component)
        alive = handle is not None and context.platform.process.is_alive(handle)
        data["components"][component] = {
            "running": alive,
            "pid": handle.pid if handle is not None else None,
            "exe": handle.exe if handle is not None else None,
        }
    try:
        selection = context.inav.resolve()
    except InavError as exc:
        selection = None
        data["inav_error"] = str(exc)
    if selection is not None:
        data["inav"] = {
            "version": selection.install.version,
            "build": selection.install.build,
            "path": str(selection.install.path),
            "eeprom": str(selection.eeprom),
            "source": selection.source,
        }
    try:
        data["config"] = {"path": str(context.config.config_path), "loaded": True}
        context.config.load()
    except ConfigError as exc:
        data["config"] = {"path": str(context.config.config_path), "loaded": False, "error": str(exc)}

    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    print(f"platform  {context.platform.id}")
    for component, info in data["components"].items():
        state = f"running pid={info['pid']}" if info["running"] else "stopped"
        print(f"{component:9} {state}")
    if selection is not None:
        print(f"inav      {selection.install.version} ({selection.source})")
        print(f"eeprom    {selection.eeprom}")
    elif "inav_error" in data:
        print(f"inav      error: {data['inav_error']}")
    print(f"config    {context.config.config_path}")
    return 0


def cmd_doctor(context: Context) -> int:
    print(f"platform  {context.platform.id}")
    capabilities = context.platform.keyboard.capabilities()
    print(
        f"keyboard  backend={context.platform.keyboard.backend} "
        f"global={capabilities.global_keyboard} foreground={capabilities.foreground_gate}"
    )
    xplane = context.platform.xplane.locate()
    print(f"xplane    {xplane.path if xplane else 'not found'}")
    installs = context.inav.list()
    print(f"inav      {', '.join(item.version for item in installs) or 'none'}")
    try:
        context.config.load()
        print(f"config    {context.config.config_path} (present)")
    except ConfigError as exc:
        print(f"config    ERROR {exc}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    context = Context(Path.cwd())
    try:
        if args.command == "inav":
            return cmd_inav(context, args)
        if args.command == "config":
            return cmd_config(context, args)
        if args.command == "setup":
            return cmd_setup(context, args)
        if args.command == "start":
            return cmd_start(context, args)
        if args.command == "stop":
            return cmd_stop(context, args)
        if args.command == "status":
            return cmd_status(context, args)
        if args.command == "doctor":
            return cmd_doctor(context)
    except (InavError, ConfigError, StartupError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
