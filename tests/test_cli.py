"""CLI parser and INAV command tests."""

from __future__ import annotations

import io
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from hidrx.apps.cli import build_parser, cmd_inav
from hidrx.models import InavInstall, ProcessHandle
from hidrx.platform.fake import FakeInavLocator
from hidrx.services.inav import InavService
from hidrx.services.runtime import RuntimeStore


class ParserTests(unittest.TestCase):
    def test_start_flags(self) -> None:
        args = build_parser().parse_args(
            ["start", "bridge", "--input", "gamepad", "--inav-version", "10.0.0"]
        )
        self.assertEqual(args.component, "bridge")
        self.assertEqual(args.input, "gamepad")
        self.assertEqual(args.inav_version, "10.0.0")

    def test_defaults(self) -> None:
        args = build_parser().parse_args(["status"])
        self.assertFalse(args.json)


class InavCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.install = InavInstall("10.0.0", "build", root / "inav_SITL.exe", "fake")
        self.locator = FakeInavLocator([self.install])
        self.service = InavService(
            locator=self.locator,
            config_dir=root / "config",
            runtime_dir=root / "config" / "runtime",
            env={},
            platform_id="fake",
        )
        self.context = SimpleNamespace(inav=self.service, platform=SimpleNamespace(inav=self.locator))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = cmd_inav(self.context, Namespace(inav_command="list"))
        self.assertEqual(code, 0)
        self.assertIn("10.0.0", output.getvalue())

    def test_use(self) -> None:
        with redirect_stdout(io.StringIO()):
            code = cmd_inav(self.context, Namespace(inav_command="use", version="10.0.0"))
        self.assertEqual(code, 0)
        self.assertEqual(self.service.read_active()["version"], "10.0.0")

    def test_check(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = cmd_inav(
                self.context,
                Namespace(inav_command="check", path=self.install.path),
            )
        self.assertEqual(code, 0)
        self.assertIn("10.0.0", output.getvalue())


class RuntimeStoreTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp))
            process = ProcessHandle(pid=42, start_time=1.5, exe="x.exe")
            store.save("sitl", process)
            loaded = store.load("sitl")
            self.assertEqual(loaded, process)
            store.remove("sitl")
            self.assertIsNone(store.load("sitl"))


if __name__ == "__main__":
    unittest.main()
