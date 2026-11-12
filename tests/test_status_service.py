"""Status service tests with the fake platform."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hidrx.actions import KEYBOARD_ACTIONS
from hidrx.models import InavInstall, ProcessHandle, ProcessInfo, XPlaneInfo
from hidrx.platform.fake import FakeInavLocator, FakePaths, FakePlatform, FakeXPlane
from hidrx.services.config import ConfigService
from hidrx.services.inav import InavService
from hidrx.services.runtime import RuntimeStore
from hidrx.services.status import StatusService


class StatusServiceTests(unittest.TestCase):
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
        self.platform.process.open_ports = {5760, 5761, 5762, 5763}
        self.platform.xplane = FakeXPlane(
            info=XPlaneInfo(path=self.root / "X-Plane 11", version="11.55"),
            process=ProcessInfo(ProcessHandle(123, 1.0, "X-Plane.exe"), "X-Plane.exe"),
        )
        self.install = InavInstall("10.0.0", "build", self.root / "inav_SITL.exe", "fake")
        self.inav = InavService(
            locator=FakeInavLocator([self.install]),
            config_dir=self.paths.config_dir,
            runtime_dir=self.paths.runtime_dir,
            env={},
            platform_id="fake",
        )
        config_path = self.paths.config_dir / "hid2msp_inav.json"
        config_path.parent.mkdir(parents=True)
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
        self.config = ConfigService(config_path, "fake", "fake")
        self.store = RuntimeStore(self.paths.run_dir)
        handle = ProcessHandle(999, 1.0, "inav_SITL.exe")
        self.store.save("sitl", handle)
        self.platform.process.alive[999] = handle

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collect(self) -> None:
        report = StatusService(self.platform, self.inav, self.config, self.store).collect()
        self.assertTrue(report.components["sitl"].running)
        self.assertFalse(report.components["bridge"].running)
        self.assertEqual(report.inav["version"], "10.0.0")
        self.assertTrue(report.config["loaded"])
        self.assertTrue(report.ports[5760])
        self.assertEqual(report.xplane["version"], "11.55")
        data = report.as_dict()
        self.assertEqual(data["components"]["sitl"]["pid"], 999)


if __name__ == "__main__":
    unittest.main()
