"""SITL and bridge service tests with the fake platform."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hidrx.actions import KEYBOARD_ACTIONS
from hidrx.core.startup import StartupError

from hidrx.models import InavInstall
from hidrx.platform.fake import FakeInavLocator, FakePaths, FakeProcessManager
from hidrx.services.bridge import BridgeService
from hidrx.services.config import ConfigService
from hidrx.services.inav import InavService
from hidrx.services.sitl import SitlError, SitlService


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = FakePaths(
            repo_root=self.root,
            config_dir=self.root / "config",
            runtime_dir=self.root / "config" / "runtime",
            logs_dir=self.root / "logs",
            run_dir=self.root / "run",
        )
        self.install = InavInstall("10.0.0", "build", self.root / "inav_SITL.exe", "fake")
        self.inav = InavService(
            locator=FakeInavLocator([self.install]),
            config_dir=self.paths.config_dir,
            runtime_dir=self.paths.runtime_dir,
            env={},
            platform_id="fake",
        )
        self.selection = self.inav.resolve()
        self.selection.eeprom.parent.mkdir(parents=True)
        self.selection.eeprom.write_bytes(b"eeprom")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_sitl_start_and_stop(self) -> None:
        process = FakeProcessManager(ports_after_spawn={5760, 5761, 5762, 5763})
        service = SitlService(process=process, paths=self.paths, inav=self.inav)
        handle = service.start(self.selection)
        self.assertTrue(process.is_alive(handle))
        self.assertIn(f"--path={self.selection.eeprom}", process.spawned[-1].argv)
        service.stop(handle)
        self.assertFalse(process.is_alive(handle))

    def test_sitl_refuses_busy_ports(self) -> None:
        process = FakeProcessManager(open_ports={5760})
        service = SitlService(process=process, paths=self.paths, inav=self.inav)
        with self.assertRaises(SitlError):
            service.start(self.selection)

    def test_sitl_stops_child_when_ports_never_open(self) -> None:
        process = FakeProcessManager()
        service = SitlService(process=process, paths=self.paths, inav=self.inav)
        with self.assertRaises(SitlError):
            service.start(self.selection, timeout=0.05)
        self.assertEqual(process.alive, {})

    def test_bridge_command_and_start(self) -> None:
        process = FakeProcessManager()
        service = BridgeService(
            process=process,
            paths=self.paths,
        )
        handle = service.start(self.root / "config" / "hid2msp_inav.json", "joystick")
        self.assertTrue(process.is_alive(handle))
        argv = process.spawned[-1].argv
        self.assertIn("--input", argv)
        self.assertEqual(argv[argv.index("--input") + 1], "joystick")

    def test_bridge_rejects_unknown_input(self) -> None:
        service = BridgeService(
            process=FakeProcessManager(),
            paths=self.paths,
        )
        with self.assertRaises(ValueError):
            service.command(self.root / "config.json", "nonsense")

    def test_config_service_plan(self) -> None:
        config_path = self.root / "config" / "hid2msp_inav.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "platform": "fake",
                    "keyboard": {
                        "backend": "fake",
                        "keys": {action: "a" for action in KEYBOARD_ACTIONS},
                    },
                }
            ),
            encoding="utf-8",
        )
        service = ConfigService(config_path, platform_id="fake", keyboard_backend="fake")
        plan = service.plan(service.load(), "auto")
        self.assertTrue(plan.keyboard_fallback)

    def test_config_service_rejects_foreign_platform(self) -> None:
        config_path = self.root / "config" / "foreign.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"platform": "windows", "keyboard": {"backend": "win32", "keys": {}}}),
            encoding="utf-8",
        )
        service = ConfigService(config_path, platform_id="macos", keyboard_backend="quartz")
        with self.assertRaises(StartupError):
            service.plan(service.load(), "auto")


if __name__ == "__main__":
    unittest.main()
