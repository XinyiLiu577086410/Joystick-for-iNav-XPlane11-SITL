"""Windows adapter tests (skipped on other platforms)."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from hidrx.models import ProcessHandle, ProcessSpec

if sys.platform == "win32":
    from hidrx.platform.windows.inav_locator import WindowsInavLocator, parse_version_output
    from hidrx.platform.windows.keyboard import WindowsKeyboard, normalize_combo, resolve_combo
    from hidrx.platform.windows.paths import WindowsPaths
    from hidrx.platform.windows.platform import WindowsPlatform
    from hidrx.platform.windows.processes import Win32ProcessManager, process_creation_time
    from hidrx.platform.windows.xplane import WindowsXPlane


@unittest.skipUnless(sys.platform == "win32", "Windows-only adapter")
class WindowsPathsTests(unittest.TestCase):
    def test_layout_and_ensure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = WindowsPaths.for_repo(Path(tmp))
            paths.ensure()
            self.assertTrue(paths.config_dir.is_dir())
            self.assertTrue(paths.runtime_dir.is_dir())
            self.assertTrue(paths.logs_dir.is_dir())
            self.assertTrue(paths.run_dir.is_dir())


@unittest.skipUnless(sys.platform == "win32", "Windows-only adapter")
class Win32ProcessManagerTests(unittest.TestCase):
    def test_current_process_is_alive_and_findable(self) -> None:
        manager = Win32ProcessManager()
        image = Path(sys.executable).name
        handle = ProcessHandle(os.getpid(), process_creation_time(os.getpid()) or 0.0, image)
        self.assertTrue(manager.is_alive(handle))
        self.assertTrue(manager.find("python"))

    def test_spawn_and_stop(self) -> None:
        manager = Win32ProcessManager()
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "child.log"
            handle = manager.spawn(
                ProcessSpec(
                    argv=("cmd", "/c", "ping", "-n", "6", "127.0.0.1", ">", "nul"),
                    cwd=Path(tmp),
                    log_path=log,
                )
            )
            self.assertTrue(manager.is_alive(handle))
            manager.stop(handle)
            time.sleep(0.3)
            self.assertFalse(manager.is_alive(handle))

    def test_port_listening_false_for_unused_port(self) -> None:
        self.assertFalse(Win32ProcessManager().port_listening(1))


@unittest.skipUnless(sys.platform == "win32", "Windows-only adapter")
class WindowsKeyboardTests(unittest.TestCase):
    def test_normalize_and_resolve(self) -> None:
        self.assertEqual(normalize_combo("Ctrl+Shift+Space"), "ctrl+shift+space")
        self.assertEqual(normalize_combo("shift"), "shift")
        self.assertEqual(resolve_combo("ctrl+a").label, "ctrl+a")
        with self.assertRaises(ValueError):
            normalize_combo("ctrl+")

    def test_validate_and_state(self) -> None:
        keyboard = WindowsKeyboard()
        keyboard.validate("ctrl+a")
        self.assertIsInstance(keyboard.is_down("a"), bool)
        self.assertTrue(keyboard.capabilities().global_keyboard)


@unittest.skipUnless(sys.platform == "win32", "Windows-only adapter")
class WindowsInavLocatorTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(
            parse_version_output("INAV/SITL 10.0.0 (86a0441c)"),
            ("10.0.0", "86a0441c"),
        )
        self.assertEqual(parse_version_output("no version"), ("unknown", ""))

    def test_resolve_missing_path(self) -> None:
        self.assertIsNone(WindowsInavLocator().resolve_path(Path("does-not-exist")))

    def test_discover_filters_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "INAV-Configurator_10.0.0"
            exe = root / "resources" / "sitl" / "windows" / "inav_SITL.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            locator = WindowsInavLocator(search_roots=[root])
            locator._probe = lambda path: None  # type: ignore[method-assign]
            self.assertEqual(locator.discover(), [])


@unittest.skipUnless(sys.platform == "win32", "Windows-only adapter")
class WindowsXPlaneTests(unittest.TestCase):
    def test_locate_and_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "X-Plane 11"
            root.mkdir()
            (root / "X-Plane.exe").write_bytes(b"")
            plugin = root / "Aircraft" / "NK_FPVSurfwing" / "plugins" / "INAV-X-Plane-HITL" / "64" / "win.xpl"
            plugin.parent.mkdir(parents=True)
            plugin.write_bytes(b"")
            xplane = WindowsXPlane(search_roots=[root])
            info = xplane.locate()
            self.assertIsNotNone(info)
            self.assertTrue(xplane.plugin("NK_FPVSurfwing").installed)


@unittest.skipUnless(sys.platform == "win32", "Windows-only adapter")
class WindowsPlatformTests(unittest.TestCase):
    def test_composition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            platform = WindowsPlatform.for_repo(Path(tmp))
            self.assertEqual(platform.id, "windows")
            self.assertEqual(platform.paths.repo_root, Path(tmp))
            self.assertIs(platform.xplane.process, platform.process)


if __name__ == "__main__":
    unittest.main()
