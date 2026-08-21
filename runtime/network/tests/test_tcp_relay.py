import json
from pathlib import Path
import queue
import socket
import tempfile
import threading
import time
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from runtime.network.tcp_relay import PrivateEndpoint, RelayConfig, run_relay_once


def start_echo_server():
    ready = queue.Queue()
    errors = []

    def serve():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                ready.put(listener.getsockname()[1])
                conn, _ = listener.accept()
                with conn:
                    while True:
                        try:
                            data = conn.recv(65536)
                            if not data:
                                return
                            conn.sendall(data)
                        except OSError:
                            return
        except Exception as exc:  # pragma: no cover - diagnostic path
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return ready.get(timeout=2), thread, errors


def start_sink_server():
    ready = queue.Queue()
    stop = threading.Event()
    errors = []

    def serve():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                ready.put(listener.getsockname()[1])
                conn, _ = listener.accept()
                with conn:
                    while not stop.is_set():
                        try:
                            data = conn.recv(65536)
                        except OSError:
                            return
                        if not data:
                            return
        except Exception as exc:  # pragma: no cover - diagnostic path
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return ready.get(timeout=2), thread, stop, errors


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TcpRelayTests(unittest.TestCase):
    def test_private_endpoint_rejects_public_dns_ipv6_and_wildcard(self):
        for value in (
            "8.8.8.8:50052",
            "example.com:50052",
            "[::1]:50052",
            "0.0.0.0:50052",
            "169.254.1.2:50052",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PrivateEndpoint.parse(value)
        self.assertEqual(PrivateEndpoint.parse("127.0.0.1:50052").text(), "127.0.0.1:50052")
        self.assertEqual(PrivateEndpoint.parse("192.168.1.5:50052").host, "192.168.1.5")

    def test_config_bounds_buffers_and_fault_injection(self):
        endpoint = PrivateEndpoint("127.0.0.1", 50052)
        with self.assertRaises(ValueError):
            RelayConfig(endpoint, chunk_bytes=512)
        with self.assertRaises(ValueError):
            RelayConfig(endpoint, chunk_bytes=4096, max_buffer_bytes=2048)
        with self.assertRaises(ValueError):
            RelayConfig(endpoint, one_way_delay_ms=-1)
        with self.assertRaises(ValueError):
            RelayConfig(endpoint, jitter_ms=-1)
        with self.assertRaises(ValueError):
            RelayConfig(endpoint, disconnect_after_bytes=0)
        with self.assertRaises(ValueError):
            RelayConfig(endpoint, disconnect_after_seconds=0)
        with self.assertRaises(ValueError):
            RelayConfig(endpoint, connect_timeout_seconds=0)

    def test_real_loopback_relay_forwards_and_counts_exact_bytes(self):
        target_port, target_thread, target_errors = start_echo_server()
        ready = queue.Queue()
        holder = {}
        errors = []
        payload = (b"ComputeMesh-relay-probe-" * 4096) + b"end"
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "relay.json"
            config = RelayConfig(
                target=PrivateEndpoint("127.0.0.1", target_port),
                listen_port=0,
                chunk_bytes=4096,
                max_buffer_bytes=16 * 1024,
            )

            def run():
                try:
                    holder["metrics"] = run_relay_once(
                        config,
                        on_ready=lambda endpoint: ready.put(endpoint),
                        metrics_path=metrics_path,
                    )
                except Exception as exc:  # pragma: no cover - diagnostic path
                    errors.append(exc)

            relay_thread = threading.Thread(target=run, daemon=True)
            relay_thread.start()
            endpoint = ready.get(timeout=2)
            with socket.create_connection((endpoint.host, endpoint.port), timeout=2) as client:
                client.sendall(payload)
                client.shutdown(socket.SHUT_WR)
                chunks = []
                while True:
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
            relay_thread.join(timeout=5)
            target_thread.join(timeout=5)
            self.assertFalse(relay_thread.is_alive())
            self.assertFalse(errors)
            self.assertFalse(target_errors)
            self.assertEqual(b"".join(chunks), payload)
            metrics = holder["metrics"]
            self.assertEqual(metrics.termination["reason"], "eof")
            self.assertEqual(metrics.traffic["coordinator_to_worker_bytes"], len(payload))
            self.assertEqual(metrics.traffic["worker_to_coordinator_bytes"], len(payload))
            self.assertEqual(metrics.traffic["total_forwarded_bytes"], len(payload) * 2)
            self.assertIsNotNone(metrics.connected_at)
            # A very fast Windows loopback run may begin/end inside one
            # monotonic-clock tick, so zero is a valid measured duration.
            self.assertGreaterEqual(metrics.active_elapsed_ms, 0.0)
            self.assertGreaterEqual(metrics.total_elapsed_ms, metrics.setup_elapsed_ms)
            persisted = json.loads(metrics_path.read_text(encoding="utf-8"))
            self.assertNotIn(payload[:20].decode("ascii"), json.dumps(persisted))

    def test_setup_wait_is_separate_from_active_relay_time(self):
        target_port, target_thread, target_errors = start_echo_server()
        ready = queue.Queue()
        holder = {}
        config = RelayConfig(target=PrivateEndpoint("127.0.0.1", target_port), listen_port=0)
        relay_thread = threading.Thread(
            target=lambda: holder.setdefault(
                "metrics", run_relay_once(config, on_ready=lambda endpoint: ready.put(endpoint))
            ),
            daemon=True,
        )
        relay_thread.start()
        endpoint = ready.get(timeout=2)
        time.sleep(0.12)
        with socket.create_connection((endpoint.host, endpoint.port), timeout=2) as client:
            client.sendall(b"timing")
            client.shutdown(socket.SHUT_WR)
            self.assertEqual(client.recv(1024), b"timing")
            while client.recv(1024):
                pass
        relay_thread.join(timeout=5)
        target_thread.join(timeout=5)
        metrics = holder["metrics"]
        self.assertGreaterEqual(metrics.setup_elapsed_ms, 100.0)
        self.assertGreaterEqual(metrics.total_elapsed_ms, metrics.setup_elapsed_ms)
        self.assertLess(metrics.active_elapsed_ms, metrics.total_elapsed_ms)
        self.assertFalse(target_errors)

    def test_delay_is_pipelined_and_content_free(self):
        target_port, target_thread, target_errors = start_echo_server()
        ready = queue.Queue()
        holder = {}
        config = RelayConfig(
            target=PrivateEndpoint("127.0.0.1", target_port),
            listen_port=0,
            one_way_delay_ms=20,
            jitter_ms=0,
            chunk_bytes=1024,
            max_buffer_bytes=8 * 1024,
        )
        relay_thread = threading.Thread(
            target=lambda: holder.setdefault(
                "metrics", run_relay_once(config, on_ready=lambda endpoint: ready.put(endpoint))
            ),
            daemon=True,
        )
        relay_thread.start()
        endpoint = ready.get(timeout=2)
        started = time.monotonic()
        with socket.create_connection((endpoint.host, endpoint.port), timeout=2) as client:
            client.sendall(b"x" * 4096)
            client.shutdown(socket.SHUT_WR)
            response = b""
            while True:
                chunk = client.recv(8192)
                if not chunk:
                    break
                response += chunk
        elapsed = time.monotonic() - started
        relay_thread.join(timeout=5)
        target_thread.join(timeout=5)
        self.assertEqual(response, b"x" * 4096)
        self.assertGreaterEqual(elapsed, 0.025)
        self.assertFalse(target_errors)
        self.assertEqual(holder["metrics"].configured["one_way_delay_ms"], 20.0)

    def test_disconnect_after_bytes_is_recorded(self):
        target_port, target_thread, target_errors = start_echo_server()
        ready = queue.Queue()
        holder = {}
        config = RelayConfig(
            target=PrivateEndpoint("127.0.0.1", target_port),
            listen_port=0,
            disconnect_after_bytes=1024,
            chunk_bytes=1024,
            max_buffer_bytes=4096,
        )
        relay_thread = threading.Thread(
            target=lambda: holder.setdefault(
                "metrics", run_relay_once(config, on_ready=lambda endpoint: ready.put(endpoint))
            ),
            daemon=True,
        )
        relay_thread.start()
        endpoint = ready.get(timeout=2)
        with socket.create_connection((endpoint.host, endpoint.port), timeout=2) as client:
            try:
                client.sendall(b"z" * 8192)
                client.shutdown(socket.SHUT_WR)
                while client.recv(8192):
                    pass
            except OSError:
                pass
        relay_thread.join(timeout=5)
        target_thread.join(timeout=5)
        self.assertFalse(relay_thread.is_alive())
        self.assertEqual(holder["metrics"].termination["reason"], "disconnect_after_bytes")
        self.assertGreaterEqual(holder["metrics"].traffic["total_forwarded_bytes"], 1024)
        self.assertFalse(target_errors)

    def test_disconnect_after_seconds_starts_after_connection(self):
        target_port, target_thread, target_stop, target_errors = start_sink_server()
        ready = queue.Queue()
        holder = {}
        config = RelayConfig(
            target=PrivateEndpoint("127.0.0.1", target_port),
            listen_port=0,
            disconnect_after_seconds=0.10,
        )
        relay_thread = threading.Thread(
            target=lambda: holder.setdefault(
                "metrics", run_relay_once(config, on_ready=lambda endpoint: ready.put(endpoint))
            ),
            daemon=True,
        )
        relay_thread.start()
        endpoint = ready.get(timeout=2)
        time.sleep(0.12)
        client = socket.create_connection((endpoint.host, endpoint.port), timeout=2)
        relay_thread.join(timeout=5)
        try:
            client.close()
        finally:
            target_stop.set()
            target_thread.join(timeout=5)
        self.assertFalse(relay_thread.is_alive())
        metrics = holder["metrics"]
        self.assertEqual(metrics.termination["reason"], "disconnect_after_seconds")
        self.assertGreaterEqual(metrics.setup_elapsed_ms, 100.0)
        self.assertGreaterEqual(metrics.active_elapsed_ms, 80.0)
        self.assertFalse(target_errors)

    def test_connect_failure_returns_and_persists_content_free_evidence(self):
        target_port = unused_loopback_port()
        ready = queue.Queue()
        holder = {}
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "connect-error.json"
            config = RelayConfig(
                target=PrivateEndpoint("127.0.0.1", target_port),
                listen_port=0,
                connect_timeout_seconds=0.5,
            )
            relay_thread = threading.Thread(
                target=lambda: holder.setdefault(
                    "metrics",
                    run_relay_once(
                        config,
                        on_ready=lambda endpoint: ready.put(endpoint),
                        metrics_path=metrics_path,
                    ),
                ),
                daemon=True,
            )
            relay_thread.start()
            endpoint = ready.get(timeout=2)
            with socket.create_connection((endpoint.host, endpoint.port), timeout=2):
                pass
            relay_thread.join(timeout=5)
            self.assertFalse(relay_thread.is_alive())
            metrics = holder["metrics"]
            self.assertEqual(metrics.termination["reason"], "connect_error")
            self.assertIsNone(metrics.connected_at)
            self.assertEqual(metrics.active_elapsed_ms, 0.0)
            self.assertEqual(metrics.traffic["total_forwarded_bytes"], 0)
            persisted = json.loads(metrics_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["termination"]["reason"], "connect_error")
            self.assertRegex(persisted["termination"]["message"], r"^(errno=-?[0-9]+|[A-Za-z]+Error)$")

    def test_metrics_schema_accepts_content_free_record(self):
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "relay_metrics.schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        document = {
            "schema_version": 1,
            "started_at": "2026-08-21T20:00:00Z",
            "connected_at": "2026-08-21T20:00:00.100Z",
            "ended_at": "2026-08-21T20:00:01Z",
            "listen": "127.0.0.1:50053",
            "target": "192.168.1.20:50052",
            "setup_elapsed_ms": 100.0,
            "active_elapsed_ms": 900.0,
            "total_elapsed_ms": 1000.0,
            "configured": {
                "one_way_delay_ms": 10.0,
                "jitter_ms": 2.0,
                "seed": 1,
                "chunk_bytes": 65536,
                "max_buffer_bytes": 8388608,
                "disconnect_after_bytes": None,
                "disconnect_after_seconds": None,
                "connect_timeout_seconds": 10.0,
            },
            "traffic": {
                "coordinator_to_worker_bytes": 100,
                "worker_to_coordinator_bytes": 200,
                "total_forwarded_bytes": 300,
            },
            "termination": {"reason": "eof", "error_type": None, "message": None},
        }
        validator.validate(document)
        document["payload"] = "must not exist"
        self.assertTrue(list(validator.iter_errors(document)))

    def test_metrics_schema_accepts_connect_error_without_connected_timestamp(self):
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "relay_metrics.schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        document = {
            "schema_version": 1,
            "started_at": "2026-08-21T20:00:00Z",
            "connected_at": None,
            "ended_at": "2026-08-21T20:00:00.050Z",
            "listen": "127.0.0.1:50053",
            "target": "127.0.0.1:50052",
            "setup_elapsed_ms": 50.0,
            "active_elapsed_ms": 0.0,
            "total_elapsed_ms": 50.0,
            "configured": {
                "one_way_delay_ms": 0.0,
                "jitter_ms": 0.0,
                "seed": 1,
                "chunk_bytes": 65536,
                "max_buffer_bytes": 8388608,
                "disconnect_after_bytes": None,
                "disconnect_after_seconds": None,
                "connect_timeout_seconds": 1.0,
            },
            "traffic": {
                "coordinator_to_worker_bytes": 0,
                "worker_to_coordinator_bytes": 0,
                "total_forwarded_bytes": 0,
            },
            "termination": {"reason": "connect_error", "error_type": "ConnectionRefusedError", "message": "errno=111"},
        }
        validator.validate(document)


if __name__ == "__main__":
    unittest.main()
