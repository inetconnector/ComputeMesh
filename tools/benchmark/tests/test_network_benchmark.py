import importlib.util
import json
import socket
import sys
import threading
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

MODULE_PATH = Path(__file__).resolve().parents[1] / "network_benchmark.py"
spec = importlib.util.spec_from_file_location("cm_network_benchmark", MODULE_PATH)
nb = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = nb
spec.loader.exec_module(nb)


def start_server(max_transfer_bytes=1024 * 1024, node_id=None):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def worker():
        try:
            conn, _ = listener.accept()
            with conn:
                nb.handle_connection(conn, max_transfer_bytes=max_transfer_bytes, node_id=node_id)
        finally:
            listener.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return port, thread


class NetworkBenchmarkTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(nb.percentile([1.0], 0.95), 1.0)
        self.assertEqual(nb.percentile([1.0, 2.0, 3.0], 0.5), 2.0)

    def test_loopback_client_legacy_server_remains_compatible(self):
        port, thread = start_server()
        result = nb.run_client(
            "127.0.0.1",
            port,
            profile_revision=4,
            rtt_samples=5,
            ping_bytes=16,
            transfer_bytes=64 * 1024,
            transfer_repeats=2,
        )
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["benchmark_name"], "tcp_network_path")
        self.assertEqual(result["profile_revision"], 4)
        self.assertNotIn("peer_node_id", result["conditions"])
        self.assertGreater(result["metrics"]["rtt_ms_p50"], 0)
        self.assertGreater(result["metrics"]["upload_mbps_p50"], 0)
        self.assertGreater(result["metrics"]["download_mbps_p50"], 0)
        self.assertEqual(len(result["raw_samples"]), 9)

    def test_server_reported_peer_identity_is_recorded(self):
        port, thread = start_server(node_id="lab-worker01")
        result = nb.run_client(
            "127.0.0.1",
            port,
            profile_revision=7,
            local_node_id="lab-coord001",
            expected_peer_node_id="lab-worker01",
            rtt_samples=1,
            transfer_bytes=4096,
            transfer_repeats=1,
        )
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["conditions"]["local_node_id"], "lab-coord001")
        self.assertEqual(result["conditions"]["peer_node_id"], "lab-worker01")
        self.assertEqual(
            result["conditions"]["peer_identity_binding"],
            "unauthenticated_server_report_v1",
        )

    def test_expected_peer_identity_mismatch_is_rejected(self):
        port, thread = start_server(node_id="lab-worker01")
        with self.assertRaisesRegex(RuntimeError, "peer node ID mismatch"):
            nb.run_client(
                "127.0.0.1",
                port,
                profile_revision=1,
                expected_peer_node_id="lab-other001",
                rtt_samples=1,
                transfer_bytes=4096,
                transfer_repeats=1,
            )
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_expected_peer_requires_newer_identity_capable_server(self):
        port, thread = start_server()
        with self.assertRaisesRegex(RuntimeError, "did not report a node ID"):
            nb.run_client(
                "127.0.0.1",
                port,
                profile_revision=1,
                expected_peer_node_id="lab-worker01",
                rtt_samples=1,
                transfer_bytes=4096,
                transfer_repeats=1,
            )
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_malformed_identity_query_closes_connection_after_error(self):
        port, thread = start_server(node_id="lab-worker01")
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        try:
            nb.send_header(sock, b"I", 4)
            sock.sendall(b"JUNK")
            # The server attempts to send E before closing, but a TCP close with
            # unread inbound bytes may surface as an immediate RST on Windows.
            # Either an E frame followed by close, or immediate close/reset,
            # proves the malformed stream is not resynchronized as valid input.
            try:
                op, size = nb.recv_header(sock)
                self.assertEqual((op, size), (b"E", 0))
                try:
                    trailing = sock.recv(1)
                except ConnectionResetError:
                    trailing = b""
                self.assertEqual(trailing, b"")
            except ConnectionError:
                pass
        finally:
            sock.close()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_node_id_validation_is_bounded(self):
        self.assertEqual(nb._node_id(" lab-a ", "node"), "lab-a")
        with self.assertRaises(ValueError):
            nb._node_id("", "node", required=True)
        with self.assertRaises(ValueError):
            nb._node_id("a\nnode", "node")
        with self.assertRaises(ValueError):
            nb._node_id("x" * 129, "node")

    def test_server_rejects_oversized_transfer(self):
        port, thread = start_server(max_transfer_bytes=1024)
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        try:
            nb.send_header(sock, b"D", 2048)
            op, size = nb.recv_header(sock)
            self.assertEqual(op, b"E")
            self.assertEqual(size, 0)
            nb.send_header(sock, b"Q", 0)
        finally:
            sock.close()
        thread.join(timeout=2)

    def test_result_matches_benchmark_schema(self):
        port, thread = start_server(node_id="lab-worker01")
        result = nb.run_client(
            "127.0.0.1",
            port,
            profile_revision=0,
            local_node_id="lab-coord001",
            rtt_samples=1,
            transfer_bytes=4096,
            transfer_repeats=1,
        )
        thread.join(timeout=2)
        schema_path = Path(__file__).resolve().parents[3] / "protocol" / "schemas" / "benchmark_result.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["conditions"]["warm_state"], "warm")


if __name__ == "__main__":
    unittest.main()
