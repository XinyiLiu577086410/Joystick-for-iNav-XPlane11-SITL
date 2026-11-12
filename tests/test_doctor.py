"""Doctor service tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hidrx.actions import KEYBOARD_ACTIONS
from hidrx.models import InavInstall, PluginInfo, ProcessHandle, ProcessInfo, XPlaneInfo
from hidrx.platform.fake import FakeInavLocator, FakePaths, FakePlatform, FakeXPlane
from hidrx.services.config import ConfigService
from hidrx.services.doctor import DoctorService
from hidrx.services.inav import InavService
from hidrx.services.runtime import RuntimeStore


class DoctorServiceTests(unittest.TestCase):
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
        self.platform = FakePlatform(paths=self.paths)
        self.platform.xplane = FakeXPlane(
            info=XPlaneInfo(path=self.root / "X-Plane 11", version="11.55"),
            process=ProcessInfo(ProcessHandle(1, 1.0, "X-Plane.exe"), "X-Plane.exe"),
            plugin_info=PluginInfo(installed=True, path=self.root / "win.xpl"),
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
        self.config_path = self.paths.config_dir / "hid2msp_inav.json"
        self.config_path.write_text(
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
        self.config = ConfigService(self.config_path, "fake", "fake")
        self.store = RuntimeStore(self.paths.run_dir)
        self.doctor = DoctorService(self.platform, self.inav, self.config, self.store)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collect_is_healthy(self) -> None:
        checks = self.doctor.collect()
        names = {check.name for check in checks}
        self.assertIn("platform", names)
        self.assertIn("eeprom", names)
        self.assertEqual(self.doctor.failed(), [])

    def test_missing_config_is_failure(self) -> None:
        self.config_path.unlink()
        failing = [check.name for check in self.doctor.collect() if not check.ok and not check.warning]
        self.assertIn("config", failing)


if __name__ == "__main__":
    unittest.main()
