"""POSIX process adapter tests (macOS/Linux CI)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from hidrx.models import ProcessSpec
from hidrx.platform.posix.processes import PosixProcessManager, process_exists


@unittest.skipUnless(os.name == "posix", "POSIX-only adapter")
class PosixProcessManagerTests(unittest.TestCase):
    def test_current_process_is_alive(self) -> None:
        manager = PosixProcessManager()
        self.assertTrue(process_exists(os.getpid()))
        self.assertTrue(manager.find("python"))

    def test_spawn_find_stop(self) -> None:
        manager = PosixProcessManager()
        with tempfile.TemporaryDirectory() as tmp:
            handle = manager.spawn(
                ProcessSpec(
                    argv=("/bin/sh", "-c", "sleep 10"),
                    cwd=Path(tmp),
                    log_path=Path(tmp) / "child.log",
                )
            )
            self.assertTrue(manager.is_alive(handle))
            self.assertTrue(manager.find("sh"))
            manager.stop(handle)
            self.assertFalse(manager.is_alive(handle))

    def test_port_listening_false(self) -> None:
        self.assertFalse(PosixProcessManager().port_listening(1))


if __name__ == "__main__":
    unittest.main()
