import importlib.util
import socket
import sys
import threading
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "network_benchmark.py"
spec = importlib.util.spec_from_file_location("cm_network_benchmark", MODULE_PATH)
nb = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = nb
spec.loader.exec_module(nb)


def start_server(max_transfer_bytes=1024 * 1024):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def worker():
        try:
            conn, _ = listener.accept()
            with conn:
                nb.handle_connection(conn, max_transfer_bytes=max_transfer_bytes)
        finally:
            listener.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return port, thread


class NetworkBenchmarkTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(nb.percentile([1.0], 0.95), 1.0)
        self.assertEqual(nb.percentile([1.0, 2.0, 3.0], 0.5), 2.0)

    def test_loopback_client(self):
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
        self.assertGreater(result["metrics"]["rtt_ms_p50"], 0)
        self.assertGreater(result["metrics"]["upload_mbps_p50"], 0)
        self.assertGreater(result["metrics"]["download_mbps_p50"], 0)
        self.assertEqual(len(result["raw_samples"]), 9)

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

    def test_result_matches_benchmark_schema_shape(self):
        port, thread = start_server()
        result = nb.run_client(
            "127.0.0.1",
            port,
            profile_revision=0,
            rtt_samples=1,
            transfer_bytes=4096,
            transfer_repeats=1,
        )
        thread.join(timeout=2)
        self.assertEqual(
            set(result),
            {"schema_version", "run_id", "benchmark_name", "captured_at", "profile_revision", "conditions", "metrics", "raw_samples"},
        )
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["conditions"]["warm_state"], "warm")


if __name__ == "__main__":
    unittest.main()
