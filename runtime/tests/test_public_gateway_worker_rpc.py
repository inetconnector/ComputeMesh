import unittest
import multiprocessing
import socket
import time
import json
from typing import Optional

from runtime.zero_trust_worker import ZeroTrustWorkerCommunicator

def run_worker_rpc_server(
    port_queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
    hmac_secret: str,
    worker_id: str,
    cluster_id: str,
    client_cert_cn: str,
    auth_token: str,
    session_id_queue: multiprocessing.Queue
):
    # Initialize the worker's ZeroTrust module
    zt = ZeroTrustWorkerCommunicator(hmac_secret=hmac_secret)
    session = zt.initiate_worker_handshake(worker_id, cluster_id, client_cert_cn, auth_token)
    session_id_queue.put(session.session_id)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    port_queue.put(port)
    sock.listen(1)
    sock.settimeout(0.5)

    processed_jobs = set()

    while not stop_event.is_set():
        try:
            conn, addr = sock.accept()
            with conn:
                data = b""
                conn.settimeout(1.0)
                while True:
                    try:
                        chunk = conn.recv(1024)
                        if not chunk:
                            break
                        data += chunk
                        if b'\n' in data:
                            break
                    except socket.timeout:
                        break

                if data:
                    try:
                        req_payload = json.loads(data.decode('utf-8').strip())

                        # Verify the gateway's request
                        is_valid = zt.verify_payload(
                            session_id=session.session_id,
                            payload_bytes=req_payload["payload"].encode('utf-8'),
                            signature=req_payload["signature"],
                            nonce=req_payload["nonce"],
                            timestamp=req_payload["timestamp"]
                        )

                        if is_valid:
                            inner_req = json.loads(req_payload["payload"])
                            job_id = inner_req.get("job_id")

                            if job_id in processed_jobs:
                                resp_data = {"status": "duplicate", "job_id": job_id}
                            else:
                                processed_jobs.add(job_id)
                                resp_data = {"status": "success", "result": "computed_value", "job_id": job_id}

                            resp_bytes = json.dumps(resp_data).encode('utf-8')
                            signed_resp = zt.sign_payload(session.session_id, resp_bytes)

                            # Construct the full envelope
                            envelope = {
                                "payload": resp_bytes.decode('utf-8'),
                                "signature": signed_resp["signature"],
                                "nonce": signed_resp["nonce"],
                                "timestamp": signed_resp["timestamp"]
                            }
                            conn.sendall(json.dumps(envelope).encode('utf-8') + b'\n')
                        else:
                            # Replay or invalid signature
                            err_resp = {"error": "authentication_failed"}
                            conn.sendall(json.dumps(err_resp).encode('utf-8') + b'\n')

                    except (json.JSONDecodeError, KeyError):
                        pass
        except socket.timeout:
            continue
        except OSError:
            break
    sock.close()


class TestPublicGatewayWorkerRPC(unittest.TestCase):
    def setUp(self):
        self.stop_event = multiprocessing.Event()
        self.port_queue = multiprocessing.Queue()
        self.session_id_queue = multiprocessing.Queue()

        self.hmac_secret = "test-rpc-secret-123"
        self.worker_id = "test-worker-01"
        self.cluster_id = "test-cluster"
        self.client_cert_cn = "test.worker.mesh.local"
        self.auth_token = "valid-rpc-token-123"

        self.worker_proc = multiprocessing.Process(
            target=run_worker_rpc_server,
            args=(
                self.port_queue,
                self.stop_event,
                self.hmac_secret,
                self.worker_id,
                self.cluster_id,
                self.client_cert_cn,
                self.auth_token,
                self.session_id_queue
            )
        )
        self.worker_proc.start()
        self.port = self.port_queue.get(timeout=2.0)
        self.worker_session_id = self.session_id_queue.get(timeout=2.0)

        # Initialize gateway communicator
        self.gateway_zt = ZeroTrustWorkerCommunicator(hmac_secret=self.hmac_secret)

        # We must inject the exact session into the gateway so they share keys.
        # ZeroTrustWorkerCommunicator derives the key using the session_id.
        import hmac
        import hashlib
        session_key = hmac.new(
            self.gateway_zt._master_secret,
            f"{self.worker_session_id}:{self.worker_id}:{self.client_cert_cn}".encode("utf-8"),
            hashlib.sha256,
        ).digest()

        from runtime.zero_trust_worker import ZeroTrustWorkerSession
        self.gateway_zt._sessions[self.worker_session_id] = ZeroTrustWorkerSession(
            session_id=self.worker_session_id,
            worker_id=self.worker_id,
            cluster_id=self.cluster_id,
            client_cert_cn=self.client_cert_cn,
            session_key=session_key,
            handshake_timestamp=time.time(),
            verified=True,
            is_isolated=False,
        )

    def tearDown(self):
        self.stop_event.set()
        self.worker_proc.join(timeout=1.0)
        if self.worker_proc.is_alive():
            self.worker_proc.terminate()
            self.worker_proc.join(timeout=1.0)

    def test_happy_path_rpc_call_chain(self):
        # 1. Gateway generates signed request
        job_request = {"action": "execute", "job_id": "job-happy-001"}
        payload_bytes = json.dumps(job_request).encode('utf-8')
        signed_req = self.gateway_zt.sign_payload(self.worker_session_id, payload_bytes)

        envelope = {
            "payload": payload_bytes.decode('utf-8'),
            "signature": signed_req["signature"],
            "nonce": signed_req["nonce"],
            "timestamp": signed_req["timestamp"]
        }

        # 2. Gateway sends request to worker
        with socket.create_connection(("127.0.0.1", self.port), timeout=2.0) as sock:
            sock.sendall(json.dumps(envelope).encode('utf-8') + b'\n')

            resp_data = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                resp_data += chunk
                if b'\n' in resp_data:
                    break

        # 3. Gateway verifies worker response
        resp_envelope = json.loads(resp_data.decode('utf-8').strip())

        self.assertIn("payload", resp_envelope)
        self.assertIn("signature", resp_envelope)
        self.assertIn("nonce", resp_envelope)
        self.assertIn("timestamp", resp_envelope)

        is_valid = self.gateway_zt.verify_payload(
            session_id=self.worker_session_id,
            payload_bytes=resp_envelope["payload"].encode('utf-8'),
            signature=resp_envelope["signature"],
            nonce=resp_envelope["nonce"],
            timestamp=resp_envelope["timestamp"]
        )

        self.assertTrue(is_valid, "Worker response failed gateway signature verification")

        inner_resp = json.loads(resp_envelope["payload"])
        self.assertEqual(inner_resp["status"], "success")
        self.assertEqual(inner_resp["job_id"], "job-happy-001")

    def test_replay_attack_rejected(self):
        job_request = {"action": "execute", "job_id": "job-replay-001"}
        payload_bytes = json.dumps(job_request).encode('utf-8')
        signed_req = self.gateway_zt.sign_payload(self.worker_session_id, payload_bytes)

        envelope = {
            "payload": payload_bytes.decode('utf-8'),
            "signature": signed_req["signature"],
            "nonce": signed_req["nonce"],
            "timestamp": signed_req["timestamp"]
        }

        # Send first request (should succeed)
        with socket.create_connection(("127.0.0.1", self.port), timeout=2.0) as sock:
            sock.sendall(json.dumps(envelope).encode('utf-8') + b'\n')

            resp_data = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                resp_data += chunk
                if b'\n' in resp_data:
                    break

        resp_envelope = json.loads(resp_data.decode('utf-8').strip())
        self.assertIn("payload", resp_envelope)
        inner_resp = json.loads(resp_envelope["payload"])
        self.assertEqual(inner_resp["status"], "success")

        # Send same request again (should fail)
        with socket.create_connection(("127.0.0.1", self.port), timeout=2.0) as sock:
            sock.sendall(json.dumps(envelope).encode('utf-8') + b'\n')

            resp_data = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                resp_data += chunk
                if b'\n' in resp_data:
                    break

        err_envelope = json.loads(resp_data.decode('utf-8').strip())
        self.assertIn("error", err_envelope)
        self.assertEqual(err_envelope["error"], "authentication_failed")

    def test_crash_recovery_and_retry(self):
        # Terminate worker abruptly to simulate crash
        self.worker_proc.terminate()
        self.worker_proc.join(timeout=1.0)

        # Attempt connection (should fail)
        with self.assertRaises((ConnectionRefusedError, TimeoutError, OSError)):
            socket.create_connection(("127.0.0.1", self.port), timeout=0.5)

        # Spin up replacement worker
        new_port_queue = multiprocessing.Queue()
        new_session_id_queue = multiprocessing.Queue()
        new_worker_proc = multiprocessing.Process(
            target=run_worker_rpc_server,
            args=(
                new_port_queue,
                self.stop_event,
                self.hmac_secret,
                self.worker_id,
                self.cluster_id,
                self.client_cert_cn,
                self.auth_token,
                new_session_id_queue
            )
        )
        new_worker_proc.start()
        new_port = new_port_queue.get(timeout=2.0)
        new_worker_session_id = new_session_id_queue.get(timeout=2.0)

        import hmac
        import hashlib
        session_key = hmac.new(
            self.gateway_zt._master_secret,
            f"{new_worker_session_id}:{self.worker_id}:{self.client_cert_cn}".encode("utf-8"),
            hashlib.sha256,
        ).digest()

        from runtime.zero_trust_worker import ZeroTrustWorkerSession
        self.gateway_zt._sessions[new_worker_session_id] = ZeroTrustWorkerSession(
            session_id=new_worker_session_id,
            worker_id=self.worker_id,
            cluster_id=self.cluster_id,
            client_cert_cn=self.client_cert_cn,
            session_key=session_key,
            handshake_timestamp=time.time(),
            verified=True,
            is_isolated=False,
        )

        job_request = {"action": "execute", "job_id": "job-retry-001"}
        payload_bytes = json.dumps(job_request).encode('utf-8')
        signed_req = self.gateway_zt.sign_payload(new_worker_session_id, payload_bytes)

        envelope = {
            "payload": payload_bytes.decode('utf-8'),
            "signature": signed_req["signature"],
            "nonce": signed_req["nonce"],
            "timestamp": signed_req["timestamp"]
        }

        # Send retry to new node
        with socket.create_connection(("127.0.0.1", new_port), timeout=2.0) as sock:
            sock.sendall(json.dumps(envelope).encode('utf-8') + b'\n')

            resp_data = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                resp_data += chunk
                if b'\n' in resp_data:
                    break

        resp_envelope = json.loads(resp_data.decode('utf-8').strip())
        self.assertIn("payload", resp_envelope)

        is_valid = self.gateway_zt.verify_payload(
            session_id=new_worker_session_id,
            payload_bytes=resp_envelope["payload"].encode('utf-8'),
            signature=resp_envelope["signature"],
            nonce=resp_envelope["nonce"],
            timestamp=resp_envelope["timestamp"]
        )

        self.assertTrue(is_valid)
        inner_resp = json.loads(resp_envelope["payload"])
        self.assertEqual(inner_resp["status"], "success")

        new_worker_proc.terminate()
        new_worker_proc.join(timeout=1.0)

    def test_idempotency_lease_billing(self):
        # Two unique signed requests (different timestamps/nonces)
        # but logically the same job_id to test worker idempotency
        job_request = {"action": "execute", "job_id": "job-idem-001"}
        payload_bytes = json.dumps(job_request).encode('utf-8')

        # Request 1
        signed_req1 = self.gateway_zt.sign_payload(self.worker_session_id, payload_bytes)
        env1 = {
            "payload": payload_bytes.decode('utf-8'),
            "signature": signed_req1["signature"],
            "nonce": signed_req1["nonce"],
            "timestamp": signed_req1["timestamp"]
        }

        with socket.create_connection(("127.0.0.1", self.port), timeout=2.0) as sock:
            sock.sendall(json.dumps(env1).encode('utf-8') + b'\n')
            resp_data1 = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                resp_data1 += chunk
                if b'\n' in resp_data1:
                    break

        resp_envelope1 = json.loads(resp_data1.decode('utf-8').strip())
        self.assertIn("payload", resp_envelope1)
        inner_resp1 = json.loads(resp_envelope1["payload"])
        self.assertEqual(inner_resp1["status"], "success")

        # Sleep briefly to ensure unique timestamp/nonce
        time.sleep(0.1)

        # Request 2 (same payload, new signature)
        signed_req2 = self.gateway_zt.sign_payload(self.worker_session_id, payload_bytes)
        env2 = {
            "payload": payload_bytes.decode('utf-8'),
            "signature": signed_req2["signature"],
            "nonce": signed_req2["nonce"],
            "timestamp": signed_req2["timestamp"]
        }

        with socket.create_connection(("127.0.0.1", self.port), timeout=2.0) as sock:
            sock.sendall(json.dumps(env2).encode('utf-8') + b'\n')
            resp_data2 = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                resp_data2 += chunk
                if b'\n' in resp_data2:
                    break

        resp_envelope2 = json.loads(resp_data2.decode('utf-8').strip())
        self.assertIn("payload", resp_envelope2)
        inner_resp2 = json.loads(resp_envelope2["payload"])

        # The worker should recognize it's a duplicate job ID and not double-bill
        self.assertEqual(inner_resp2["status"], "duplicate")
        self.assertEqual(inner_resp2["job_id"], "job-idem-001")


if __name__ == "__main__":
    unittest.main()
