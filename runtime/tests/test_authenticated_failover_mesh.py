"""Real multiprocess tests for authenticated peer handshakes, verifiable worker execution, failover recovery, and idempotency.

Follows strict Rule 7: NO stubs or mocks. Uses real OS loopback sockets, separate processes, and cryptographic HMAC verification.
"""
import unittest
import multiprocessing
import socket
import time
import json
import hmac
import hashlib
from typing import Optional

from runtime.autonomous_failover_mesh import (
    AutonomousFailoverMeshFabric,
    EndToEndLatencyOptimizer,
)


def run_authenticated_worker_node(
    port_queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
    auth_secret: Optional[str] = None,
    tamper_mac: bool = False,
    node_id: str = "worker_node_auth_1",
    crash_after_first_req: bool = False,
):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    port_queue.put(port)
    sock.listen(5)
    sock.settimeout(0.5)

    processed_jobs = set()
    req_count = 0

    while not stop_event.is_set():
        try:
            conn, _ = sock.accept()
            with conn:
                conn.settimeout(1.0)
                data = b""
                while True:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break

                if not data:
                    continue

                req = json.loads(data.decode("utf-8").strip())
                req_type = req.get("type")

                if req_type == "HANDSHAKE":
                    session_id = req.get("session_id")
                    request_id = req.get("request_id")
                    target = req.get("target_node_id")

                    resp = {
                        "type": "ACK",
                        "session_id": session_id,
                        "request_id": request_id,
                        "target_node_id": target,
                    }

                    if auth_secret is not None:
                        if tamper_mac:
                            resp["auth_mac"] = "0" * 64
                        else:
                            mac_data = f"ACK:{session_id}:{request_id}:{target}".encode("utf-8")
                            resp["auth_mac"] = hmac.new(auth_secret.encode("utf-8"), mac_data, hashlib.sha256).hexdigest()

                    conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")

                elif req_type == "JOB_EXECUTE":
                    req_count += 1
                    if crash_after_first_req and req_count == 1:
                        # Abruptly crash connection without sending response
                        break

                    job_id = req.get("job_id")
                    session_id = req.get("session_id")
                    client_mac = req.get("job_mac")

                    # Verify client MAC if auth_secret configured
                    valid = True
                    if auth_secret:
                        expected_mac = hmac.new(auth_secret.encode("utf-8"), f"JOB:{job_id}:{session_id}".encode("utf-8"), hashlib.sha256).hexdigest()
                        if client_mac != expected_mac:
                            valid = False

                    if not valid:
                        resp = {"status": "error", "reason": "unauthorized_job_request", "job_id": job_id}
                    elif job_id in processed_jobs:
                        resp = {"status": "duplicate", "job_id": job_id, "result": "already_executed"}
                    else:
                        processed_jobs.add(job_id)
                        resp = {"status": "success", "job_id": job_id, "result": f"computed_val_{job_id}"}

                    if auth_secret:
                        resp_mac = hmac.new(auth_secret.encode("utf-8"), f"RESULT:{job_id}:{resp['status']}".encode("utf-8"), hashlib.sha256).hexdigest()
                        resp["result_mac"] = resp_mac

                    conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
        except socket.timeout:
            continue
        except OSError:
            break
    sock.close()


class TestAuthenticatedFailoverMesh(unittest.TestCase):
    def setUp(self):
        self.stop_events = []
        self.processes = []
        self.secret = "mesh-shared-cluster-secret-2026"
        self.optimizer = EndToEndLatencyOptimizer()

    def _start_worker(self, **kwargs):
        stop_evt = multiprocessing.Event()
        q = multiprocessing.Queue()
        p = multiprocessing.Process(
            target=run_authenticated_worker_node,
            kwargs=dict(port_queue=q, stop_event=stop_evt, **kwargs),
        )
        p.start()
        port = q.get(timeout=3.0)
        self.stop_events.append(stop_evt)
        self.processes.append(p)
        return port

    def tearDown(self):
        for evt in self.stop_events:
            evt.set()
        for p in self.processes:
            p.join(timeout=1.0)
            if p.is_alive():
                p.terminate()
                p.join(timeout=1.0)

    def test_unauthenticated_plain_ack_rejected_when_peer_auth_required(self):
        # Server sends plain ACK with no auth_mac
        port = self._start_worker(auth_secret=None)
        self.optimizer.register_route("route_unauth", "worker_auth_1", "127.0.0.1", port, 10.0, 100.0)

        fabric = AutonomousFailoverMeshFabric(
            self.optimizer,
            auth_secret=self.secret,
            require_peer_auth=True,
        )
        connected = fabric.connect_to_node("worker_auth_1")
        self.assertFalse(connected, "Plain unauthenticated ACK must be rejected fail-closed when peer auth is required")
        self.assertNotIn("worker_auth_1", fabric.active_connections)

    def test_forged_mac_ack_rejected_when_peer_auth_required(self):
        # Server sends tampered MAC
        port = self._start_worker(auth_secret=self.secret, tamper_mac=True)
        self.optimizer.register_route("route_tampered", "worker_auth_1", "127.0.0.1", port, 10.0, 100.0)

        fabric = AutonomousFailoverMeshFabric(
            self.optimizer,
            auth_secret=self.secret,
            require_peer_auth=True,
        )
        connected = fabric.connect_to_node("worker_auth_1")
        self.assertFalse(connected, "Forged MAC ACK must be rejected fail-closed")
        self.assertNotIn("worker_auth_1", fabric.active_connections)

    def test_valid_peer_auth_succeeds_with_authenticated_status(self):
        port = self._start_worker(auth_secret=self.secret)
        self.optimizer.register_route("route_valid", "worker_auth_1", "127.0.0.1", port, 10.0, 100.0)

        fabric = AutonomousFailoverMeshFabric(
            self.optimizer,
            auth_secret=self.secret,
            require_peer_auth=True,
        )
        connected = fabric.connect_to_node("worker_auth_1")
        self.assertTrue(connected)
        self.assertEqual(fabric.active_connections.get("worker_auth_1"), "route_valid_AUTHENTICATED")

    def test_authenticated_job_execution_idempotency_and_crash_failover(self):
        # Primary worker crashes on first job request
        port_primary = self._start_worker(auth_secret=self.secret, crash_after_first_req=True)
        # Backup worker executes normally
        port_backup = self._start_worker(auth_secret=self.secret)

        self.optimizer.register_route("route_prim", "worker_failover", "127.0.0.1", port_primary, 10.0, 100.0)
        self.optimizer.register_route("route_back", "worker_failover", "127.0.0.1", port_backup, 20.0, 100.0)

        fabric = AutonomousFailoverMeshFabric(
            self.optimizer,
            auth_secret=self.secret,
            require_peer_auth=True,
        )

        # Execute work: should attempt primary, catch failure, autonomously failover to backup, and succeed
        res1 = fabric.execute_work("worker_failover", "job-auth-001", {"task": "infer"})
        self.assertEqual(res1.get("status"), "success")
        self.assertEqual(res1.get("job_id"), "job-auth-001")
        self.assertEqual(res1.get("result"), "computed_val_job-auth-001")

        # Execute duplicate work: should be handled idempotently
        res2 = fabric.execute_work("worker_failover", "job-auth-001", {"task": "infer"})
        self.assertEqual(res2.get("status"), "duplicate")
        self.assertEqual(res2.get("job_id"), "job-auth-001")


if __name__ == "__main__":
    unittest.main()
