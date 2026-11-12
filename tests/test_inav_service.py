"""INAV version selection tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hidrx.models import InavInstall
from hidrx.platform.fake import FakeInavLocator
from hidrx.services.inav import InavError, InavService


class InavServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.installs = [
            InavInstall("8.0.1", "old", self.root / "8" / "inav_SITL.exe", "fake"),
            InavInstall("10.0.0", "new", self.root / "10" / "inav_SITL.exe", "fake"),
        ]
        self.locator = FakeInavLocator(self.installs)
        self.service = InavService(
            locator=self.locator,
            config_dir=self.root / "config",
            runtime_dir=self.root / "config" / "runtime",
            env={},
            platform_id="fake",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_auto_picks_highest(self) -> None:
        selection = self.service.resolve()
        self.assertEqual(selection.install.version, "10.0.0")
        self.assertEqual(selection.source, "auto")
        self.assertEqual(selection.eeprom, self.root / "config" / "runtime" / "10.0.0" / "plane.bin")

    def test_cli_path_and_version(self) -> None:
        by_path = self.service.resolve(path=self.installs[0].path)
        self.assertEqual(by_path.install.version, "8.0.1")
        self.assertEqual(by_path.source, "cli-path")
        by_version = self.service.resolve(version="10")
        self.assertEqual(by_version.install.version, "10.0.0")
        self.assertEqual(by_version.source, "cli-version")

    def test_env_and_active(self) -> None:
        env_service = InavService(
            locator=self.locator,
            config_dir=self.root / "config",
            runtime_dir=self.root / "config" / "runtime",
            env={"HIDRX_INAV_VERSION": "8.0.1"},
            platform_id="fake",
        )
        self.assertEqual(env_service.resolve().install.version, "8.0.1")
        self.service.use(self.installs[1])
        self.assertEqual(self.service.resolve().install.version, "10.0.0")
        self.assertEqual(self.service.read_active()["version"], "10.0.0")

    def test_eeprom_version_mismatch(self) -> None:
        runtime = self.root / "config" / "runtime" / "10.0.0"
        runtime.mkdir(parents=True)
        (runtime / "meta.json").write_text(json.dumps({"inav_version": "9.0.0"}), encoding="utf-8")
        with self.assertRaises(InavError):
            self.service.resolve()

    def test_ensure_eeprom_and_cli_config(self) -> None:
        selection = self.service.resolve()
        with self.assertRaises(InavError):
            self.service.ensure_eeprom(selection)
        selection.eeprom.parent.mkdir(parents=True)
        selection.eeprom.write_bytes(b"eeprom")
        self.service.ensure_eeprom(selection)
        self.service.write_meta(selection)
        self.assertEqual(self.service.read_meta("10.0.0").version, "10.0.0")

    def test_missing_version(self) -> None:
        with self.assertRaises(InavError):
            self.service.resolve(version="9.9.9")


if __name__ == "__main__":
    unittest.main()
