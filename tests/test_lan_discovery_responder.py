"""Unit tests for ComputeMesh LAN Discovery UDP Responder."""
from pathlib import Path
import socket
import sys
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.appliance.lan_discovery_responder import (
    DISCOVERY_PORT,
    DISCOVERY_PROBE_MESSAGE,
    LanDiscoveryResponder,
)


class TestLanDiscoveryResponder(unittest.TestCase):
    def test_udp_ping_pong_discovery(self) -> None:
        responder = LanDiscoveryResponder(
            node_id="test-miner-rig",
            port=8080,
            gpu_summary="NVIDIA RTX 4090 24GB",
            bind_host="127.0.0.1",
        )
        started = responder.start()
        if not started:
            self.skipTest(f"Could not bind test UDP port {DISCOVERY_PORT}")

        try:
            # Send probe from client socket
            client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client_sock.settimeout(2.0)
            client_sock.sendto(DISCOVERY_PROBE_MESSAGE.encode("utf-8"), ("127.0.0.1", DISCOVERY_PORT))

            data, _ = client_sock.recvfrom(2048)
            response = data.decode("utf-8")

            self.assertTrue(response.startswith("COMPUTEMESH_PONG:"))
            parts = response.removePrefix("COMPUTEMESH_PONG:").split(";") if hasattr(response, "removePrefix") else response.replace("COMPUTEMESH_PONG:", "").split(";")
            self.assertEqual(parts[0], "test-miner-rig")
            self.assertEqual(parts[1], "8080")
            self.assertEqual(parts[2], "NVIDIA RTX 4090 24GB")
            client_sock.close()
        finally:
            responder.stop()


if __name__ == "__main__":
    unittest.main()
