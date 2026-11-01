"""Standalone credential-verified loopback mTLS regression tests.

No dashboard or gateway imports, no external network, no persisted secrets.
"""
from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path

from runtime.network.mesh_transport import (
    MeshTunnelClient,
    MeshTunnelServer,
    generate_mesh_ca,
    generate_node_tls_credentials,
)


class TestMtlsCredentialBoundary(unittest.TestCase):
    def test_authorized_echo_and_unauthorized_client_denied(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cm-mtls-ci-") as root:
            folder = Path(root)
            ca = generate_mesh_ca(folder / "ca")
            server_creds = generate_node_tls_credentials("server_trusted", folder / "server", ca_creds=ca)
            allowed_creds = generate_node_tls_credentials("client_allowed", folder / "allowed", ca_creds=ca)
            blocked_creds = generate_node_tls_credentials("client_denied", folder / "denied", ca_creds=ca)

            echo_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            echo_sock.bind(("127.0.0.1", 0))
            echo_sock.listen(4)
            echo_sock.settimeout(0.2)
            stop = threading.Event()

            def echo() -> None:
                while not stop.is_set():
                    try:
                        conn, _ = echo_sock.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    with conn:
                        conn.settimeout(2.0)
                        try:
                            data = conn.recv(1024)
                            if data:
                                conn.sendall(b"ECHO:" + data)
                        except OSError:
                            pass

            thread = threading.Thread(target=echo, daemon=True)
            thread.start()
            server = MeshTunnelServer(
                listen_host="127.0.0.1",
                listen_port=0,
                target_host="127.0.0.1",
                target_port=echo_sock.getsockname()[1],
                server_creds=server_creds,
                allowed_client_nodes={"client_allowed"},
            )
            try:
                server_port = server.start()
                for creds, expect_reply in ((allowed_creds, True), (blocked_creds, False)):
                    with self.subTest(node=creds.node_id):
                        client = MeshTunnelClient(
                            remote_tunnel_host="127.0.0.1",
                            remote_tunnel_port=server_port,
                            client_creds=creds,
                            expected_server_node_id="server_trusted",
                        )
                        try:
                            local_port = client.start()
                            with socket.create_connection(("127.0.0.1", local_port), timeout=3.0) as s:
                                s.settimeout(3.0)
                                try:
                                    s.sendall(b"PING")
                                    payload = s.recv(1024)
                                except (ConnectionResetError, BrokenPipeError, OSError):
                                    payload = b""
                            self.assertEqual(payload, b"ECHO:PING" if expect_reply else b"")
                        finally:
                            client.stop()
            finally:
                server.stop()
                stop.set()
                echo_sock.close()
                thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
