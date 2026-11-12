"""CLI-over-TCP helper tests."""

from __future__ import annotations

import socket
import threading
import unittest

from hidrx.services.cli import run_cli


class CliSessionTests(unittest.TestCase):
    def test_send_and_save(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        received = []

        def serve() -> None:
            conn, _ = server.accept()
            conn.recv(1)
            conn.sendall(b"# ")
            buffer = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    text = line.strip().decode()
                    if not text:
                        continue
                    received.append(text)
                    if text == "save":
                        conn.sendall(b"saved\r\n")
            conn.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = run_cli(["set foo = 1", "feature"], port=port, save=True)
        server.close()
        self.assertEqual(result.sent, 2)
        self.assertEqual(received, ["set foo = 1", "feature", "save"])
        self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
