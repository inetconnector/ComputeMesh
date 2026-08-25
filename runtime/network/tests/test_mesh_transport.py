"""Unit tests for Mutual TLS (mTLS) Peer-to-Peer Encrypted Transport."""
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from runtime.network.mesh_transport import (
    MeshTunnelClient,
    MeshTunnelServer,
    generate_node_tls_credentials,
)


class TestMeshTransport(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

        # Generate credentials for coordinator and worker
        self.coord_creds = generate_node_tls_credentials("node_coord_test", self.work_dir / "coord")
        self.worker_creds = generate_node_tls_credentials("node_worker_test", self.work_dir / "worker")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_credential_generation(self) -> None:
        self.assertTrue(self.coord_creds.cert_path.exists())
        self.assertTrue(self.coord_creds.key_path.exists())
        self.assertIn(b"BEGIN CERTIFICATE", self.coord_creds.cert_pem)
        self.assertIn(b"BEGIN PRIVATE KEY", self.coord_creds.key_pem)

    def test_bidirectional_mtls_tunnel(self) -> None:
        # 1. Start a mock target echo server (simulating ggml-rpc-server)
        echo_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        echo_sock.bind(("127.0.0.1", 0))
        echo_sock.listen(5)
        echo_port = echo_sock.getsockname()[1]

        def echo_worker():
            try:
                conn, _ = echo_sock.accept()
                data = conn.recv(1024)
                conn.sendall(b"ECHO:" + data)
                conn.close()
            except Exception:
                pass
            finally:
                echo_sock.close()

        threading.Thread(target=echo_worker, daemon=True).start()

        # 2. Start MeshTunnelServer on worker side
        tunnel_server = MeshTunnelServer(
            listen_host="127.0.0.1",
            listen_port=0,
            target_host="127.0.0.1",
            target_port=echo_port,
            server_creds=self.worker_creds,
        )
        server_port = tunnel_server.start()

        # 3. Start MeshTunnelClient on coordinator side
        tunnel_client = MeshTunnelClient(
            local_listen_host="127.0.0.1",
            local_listen_port=0,
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_port,
            client_creds=self.coord_creds,
        )
        client_local_port = tunnel_client.start()

        time.sleep(0.25)

        try:
            # 4. Connect client app to local loopback port
            app_sock = socket.create_connection(("127.0.0.1", client_local_port), timeout=5)
            app_sock.sendall(b"PING_COMPUTEMESH_TENSOR")
            response = app_sock.recv(1024)
            app_sock.close()

            self.assertEqual(response, b"ECHO:PING_COMPUTEMESH_TENSOR")
            self.assertGreater(tunnel_server.total_bytes_received, 0)
            self.assertGreater(tunnel_client.total_bytes_sent, 0)
        finally:
            tunnel_client.stop()
            tunnel_server.stop()


if __name__ == "__main__":
    unittest.main()
