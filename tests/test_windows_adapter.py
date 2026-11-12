"""Windows adapter tests (skipped on other platforms)."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from hidrx.models import ProcessHandle, ProcessSpec
from hidrx.platform.windows.paths import WindowsPaths
from hidrx.platform.windows.processes import Win32ProcessManager, process_creation_time


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


if __name__ == "__main__":
    unittest.main()
