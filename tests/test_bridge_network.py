"""Real socket smoke test for the bridge MSP path."""

from __future__ import annotations

import socket
import struct
import threading
import unittest

from hidrx.core.bridge import BridgeRunner
from hidrx.core.channels import AxisMap
from hidrx.core.config import BridgeConfig, KeyboardConfig
from hidrx.core.msp import MspLink
from hidrx.platform.fake import FakeKeyboard


class FakeGamepad:
    name = "fake"
    num_axes = 1
    num_buttons = 1

    def snapshot(self):
        return [1.0], [0]

    def close(self):
        pass


class BridgeNetworkTests(unittest.TestCase):
    def test_sends_msp_set_raw_rc(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        received = {}
        ready = threading.Event()

        def serve() -> None:
            conn, _ = server.accept()
            buffer = b""
            while len(buffer) < 38:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk
            if buffer.startswith(b"$M<"):
                length = buffer[3]
                command = buffer[4]
                payload = buffer[5:5 + length]
                received["command"] = command
                received["channels"] = struct.unpack("<%dH" % (length // 2), payload)
            ready.set()
            conn.close()

        threading.Thread(target=serve, daemon=True).start()
        config = BridgeConfig(
            platform="fake",
            axes=[AxisMap(axis=0, channel=1)],
            keyboard=KeyboardConfig(enabled=False, source="auto"),
        )
        keyboard = FakeKeyboard(backend="fake")
        link = MspLink("127.0.0.1", port)
        self.assertTrue(link.connect())
        runner = BridgeRunner(
            link=link,
            config=config,
            input_source="gamepad",
            keyboard_backend=keyboard,
            gamepad_factory=FakeGamepad,
            keyboard_factory=lambda: None,  # type: ignore[arg-type]
        )
        self.assertEqual(runner.run(max_frames=1), 0)
        ready.wait(timeout=2.0)
        runner.close()
        server.close()

        self.assertEqual(received.get("command"), 200)
        self.assertEqual(received.get("channels")[0], 2000)


if __name__ == "__main__":
    unittest.main()
