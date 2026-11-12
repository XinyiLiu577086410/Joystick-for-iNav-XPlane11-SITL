"""Eeprom backup/restore tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hidrx.models import InavInstall, InavSelection
from hidrx.services.eeprom import EepromError, EepromService


class EepromTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.install = InavInstall("10.0.0", "build", self.root / "inav_SITL.exe", "fake")
        self.eeprom = self.root / "runtime" / "10.0.0" / "plane.bin"
        self.eeprom.parent.mkdir(parents=True)
        self.eeprom.write_bytes(b"original")
        self.selection = InavSelection(
            install=self.install,
            eeprom=self.eeprom,
            cli_config=None,
            source="test",
        )
        self.service = EepromService(self.root / "runtime")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_backup_list_restore_reset(self) -> None:
        backup = self.service.backup(self.selection, "before-tune")
        self.assertTrue(backup.is_file())
        self.assertEqual(self.service.list("10.0.0"), [backup])
        self.eeprom.write_bytes(b"changed")
        self.service.restore(self.selection, "before-tune")
        self.assertEqual(self.eeprom.read_bytes(), b"original")
        self.service.reset(self.selection)
        self.assertFalse(self.eeprom.exists())

    def test_backup_requires_file(self) -> None:
        self.eeprom.unlink()
        with self.assertRaises(EepromError):
            self.service.backup(self.selection)

    def test_invalid_name(self) -> None:
        with self.assertRaises(EepromError):
            self.service.backup(self.selection, "../escape")

    def test_missing_backup(self) -> None:
        with self.assertRaises(EepromError):
            self.service.restore(self.selection, "missing")


if __name__ == "__main__":
    unittest.main()
