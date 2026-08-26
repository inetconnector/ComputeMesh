"""Unit tests for Mutual TLS (mTLS) Peer-to-Peer Encrypted Transport."""
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time
import unittest

from runtime.network.mesh_transport import (
    MeshTunnelClient,
    MeshTunnelServer,
    generate_mesh_ca,
    generate_node_tls_credentials,
)


class TestMeshTransport(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

        # Generate shared Mesh CA and credentials for coordinator and worker
        self.ca_creds = generate_mesh_ca(self.work_dir / "ca")
        self.coord_creds = generate_node_tls_credentials("node_coord_test", self.work_dir / "coord", ca_creds=self.ca_creds)
        self.worker_creds = generate_node_tls_credentials("node_worker_test", self.work_dir / "worker", ca_creds=self.ca_creds)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_credential_generation(self) -> None:
        self.assertTrue(self.coord_creds.cert_path.exists())
        self.assertTrue(self.coord_creds.key_path.exists())
        self.assertTrue(self.coord_creds.ca_cert_path.exists())
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
                if data:
                    conn.sendall(b"ECHO:" + data)
                try:
                    conn.recv(1024)
                except Exception:
                    pass
                conn.close()
            except Exception:
                pass
            finally:
                try:
                    echo_sock.close()
                except Exception:
                    pass

        threading.Thread(target=echo_worker, daemon=True).start()

        # 2. Start MeshTunnelServer on worker side with allowed client nodes check
        tunnel_server = MeshTunnelServer(
            listen_host="127.0.0.1",
            listen_port=0,
            target_host="127.0.0.1",
            target_port=echo_port,
            server_creds=self.worker_creds,
            allowed_client_nodes={"node_coord_test"},
        )
        server_port = tunnel_server.start()

        # 3. Start MeshTunnelClient on coordinator side
        tunnel_client = MeshTunnelClient(
            local_listen_host="127.0.0.1",
            local_listen_port=0,
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_port,
            client_creds=self.coord_creds,
            expected_server_node_id="node_worker_test",
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

    def test_mtls_rejects_unauthorized_client_node(self) -> None:
        """Verify that server drops clients whose node_id is not in allowed_client_nodes."""
        # Untrusted client with valid CA but not in allowed_client_nodes
        rogue_creds = generate_node_tls_credentials("node_rogue_attacker", self.work_dir / "rogue", ca_creds=self.ca_creds)

        echo_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        echo_sock.bind(("127.0.0.1", 0))
        echo_sock.listen(5)
        echo_port = echo_sock.getsockname()[1]

        tunnel_server = MeshTunnelServer(
            listen_host="127.0.0.1",
            listen_port=0,
            target_host="127.0.0.1",
            target_port=echo_port,
            server_creds=self.worker_creds,
            allowed_client_nodes={"node_coord_test"},  # Only node_coord_test is allowed
        )
        server_port = tunnel_server.start()

        tunnel_client = MeshTunnelClient(
            local_listen_host="127.0.0.1",
            local_listen_port=0,
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_port,
            client_creds=rogue_creds,
        )
        client_local_port = tunnel_client.start()
        time.sleep(0.25)

        try:
            app_sock = socket.create_connection(("127.0.0.1", client_local_port), timeout=5)
            app_sock.sendall(b"UNAUTHORIZED_PAYLOAD")
            try:
                response = app_sock.recv(1024)
            except ConnectionResetError:
                response = b""
            app_sock.close()
            # Server drops connection without forwarding
            self.assertEqual(response, b"")
        finally:
            tunnel_client.stop()
            tunnel_server.stop()
            echo_sock.close()

    def test_mtls_rejects_untrusted_ca_certificate(self) -> None:
        """Verify that server rejects clients presenting certificates signed by a foreign/untrusted CA."""
        foreign_ca = generate_mesh_ca(self.work_dir / "foreign_ca")
        foreign_creds = generate_node_tls_credentials("node_coord_test", self.work_dir / "foreign_coord", ca_creds=foreign_ca)

        tunnel_server = MeshTunnelServer(
            listen_host="127.0.0.1",
            listen_port=0,
            target_host="127.0.0.1",
            target_port=9999,
            server_creds=self.worker_creds,
            allowed_client_nodes={"node_coord_test"},
        )
        server_port = tunnel_server.start()

        tunnel_client = MeshTunnelClient(
            local_listen_host="127.0.0.1",
            local_listen_port=0,
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_port,
            client_creds=foreign_creds,
        )
        client_local_port = tunnel_client.start()
        time.sleep(0.25)

        try:
            app_sock = socket.create_connection(("127.0.0.1", client_local_port), timeout=5)
            app_sock.sendall(b"FOREIGN_CA_PAYLOAD")
            try:
                response = app_sock.recv(1024)
            except ConnectionResetError:
                response = b""
            app_sock.close()
            self.assertEqual(response, b"")
        finally:
            tunnel_client.stop()
            tunnel_server.stop()


if __name__ == "__main__":
    unittest.main()
