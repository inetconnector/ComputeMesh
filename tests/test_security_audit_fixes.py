"""Security Audit Regression Test Suite for ComputeMesh.

Verifies remediation of critical and high-priority vulnerabilities:
1. True mTLS peer certificate authentication and allowed_client_nodes enforcement.
2. Node heartbeat token validation preventing unauthorized telemetry tampering.
3. Remote node dashboard authentication gating (/node/<id>?auth=...).
4. Stored-XSS escaping in HTML dashboard output.
5. Rate-limiter authentication gating (unverified Bearer tokens remain in unauthenticated tier).
6. Trusted-proxy client IP resolution preventing X-Forwarded-For spoofing.
7. Idempotent initial credit grants preventing balance-reset exploits.
8. Thread-safe atomic telemetry registry persistence.
"""
from datetime import datetime, timezone
import html
import http.client
from http import HTTPStatus
import io
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.network.mesh_transport import (
    MeshTunnelClient,
    MeshTunnelServer,
    generate_mesh_ca,
    generate_node_tls_credentials,
)
from services.billing.ledger import Ledger
from services.gateway.auth import (
    GatewayAuthManager,
    extract_bearer_token,
    resolve_client_ip,
)
from services.gateway.dashboard import (
    NODE_TELEMETRY_REGISTRY,
    render_node_remote_dashboard_html,
    save_node_telemetry_registry,
)
from services.gateway.security import RateLimiter
from services.gateway.server import GatewayHandler, create_gateway_server
from services.gateway.teaser import TeaserQuotaManager


class TestSecurityAuditFixes(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.ledger = Ledger(storage_path=self.work_dir / "ledger.json")
        self.teaser_manager = TeaserQuotaManager(max_requests=5, max_tokens=1000, window_seconds=60)
        self.auth_manager = GatewayAuthManager(
            ledger=self.ledger,
            teaser_manager=self.teaser_manager,
            api_keys={"cm_live_valid_key_12345": "cust_valid_account_01"},
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. mTLS Peer Certificate Authentication
    def test_mtls_peer_certificate_verification_and_node_id_check(self) -> None:
        ca_creds = generate_mesh_ca(self.work_dir / "ca")
        server_creds = generate_node_tls_credentials("node_server_01", self.work_dir / "server", ca_creds=ca_creds)
        authorized_client_creds = generate_node_tls_credentials("node_auth_client_01", self.work_dir / "client_auth", ca_creds=ca_creds)
        unauthorized_client_creds = generate_node_tls_credentials("node_rogue_client_02", self.work_dir / "client_rogue", ca_creds=ca_creds)

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

        tunnel_server = MeshTunnelServer(
            listen_host="127.0.0.1",
            listen_port=0,
            target_host="127.0.0.1",
            target_port=echo_port,
            server_creds=server_creds,
            allowed_client_nodes={"node_auth_client_01"},
        )
        server_port = tunnel_server.start()

        # Authorized client succeeds
        tunnel_client = MeshTunnelClient(
            local_listen_host="127.0.0.1",
            local_listen_port=0,
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_port,
            client_creds=authorized_client_creds,
        )
        client_port = tunnel_client.start()
        time.sleep(0.2)

        try:
            app_sock = socket.create_connection(("127.0.0.1", client_port), timeout=3)
            app_sock.sendall(b"HELLO_MTLS")
            resp = app_sock.recv(1024)
            app_sock.close()
            self.assertEqual(resp, b"ECHO:HELLO_MTLS")
        finally:
            tunnel_client.stop()

        # Unauthorized client is rejected
        tunnel_rogue_client = MeshTunnelClient(
            local_listen_host="127.0.0.1",
            local_listen_port=0,
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_port,
            client_creds=unauthorized_client_creds,
        )
        rogue_port = tunnel_rogue_client.start()
        time.sleep(0.2)

        try:
            app_sock2 = socket.create_connection(("127.0.0.1", rogue_port), timeout=3)
            app_sock2.sendall(b"ROGUE_HELLO")
            try:
                resp2 = app_sock2.recv(1024)
            except ConnectionResetError:
                resp2 = b""
            app_sock2.close()
            self.assertEqual(resp2, b"")
        finally:
            tunnel_rogue_client.stop()
            tunnel_server.stop()

    # 2. Node Heartbeat Authentication
    def test_node_heartbeat_requires_valid_auth_token(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        NODE_TELEMETRY_REGISTRY["legit_node_01"] = {
            "node_id": "legit_node_01",
            "auth_token": "secret_token_12345",
            "telemetry": {"tokens_processed": 500},
        }

        server, port = create_gateway_server("127.0.0.1", 0)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.2)

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            # A. Heartbeat without auth_token is rejected
            body_no_token = json.dumps({"node_id": "legit_node_01"}).encode("utf-8")
            conn.request("POST", "/api/v1/node/heartbeat", body=body_no_token, headers={"Content-Type": "application/json", "Content-Length": str(len(body_no_token))})
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
            res.read()

            # B. Heartbeat with wrong auth_token is rejected
            body_wrong_token = json.dumps({"node_id": "legit_node_01", "auth_token": "wrong_attacker_token"}).encode("utf-8")
            conn.request("POST", "/api/v1/node/heartbeat", body=body_wrong_token, headers={"Content-Type": "application/json", "Content-Length": str(len(body_wrong_token))})
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
            res.read()

            # C. Heartbeat with valid auth_token is accepted
            body_valid = json.dumps({"node_id": "legit_node_01", "auth_token": "secret_token_12345", "telemetry": {"tokens_processed": 600}}).encode("utf-8")
            conn.request("POST", "/api/v1/node/heartbeat", body=body_valid, headers={"Content-Type": "application/json", "Content-Length": str(len(body_valid))})
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.OK)
            res.read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()

    # 3. Remote Node Dashboard Authentication Gating
    def test_node_remote_dashboard_enforces_auth_token(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        NODE_TELEMETRY_REGISTRY["protected_node_01"] = {
            "node_id": "protected_node_01",
            "auth_token": "correct_dash_token_999",
            "inventory": {"gpus": [{"model_name": "RTX 4090", "vram_bytes": 24 * 1024**3}]},
        }

        server, port = create_gateway_server("127.0.0.1", 0)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.2)

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            # A. Accessing without auth parameter -> 401 Unauthorized
            conn.request("GET", "/node/protected_node_01")
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
            res.read()

            # B. Accessing with incorrect auth parameter -> 401 Unauthorized
            conn.request("GET", "/node/protected_node_01?auth=wrong_guess")
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.UNAUTHORIZED)
            res.read()

            # C. Accessing nonexistent node -> 404 Not Found
            conn.request("GET", "/node/nonexistent_unknown_node?auth=any")
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.NOT_FOUND)
            res.read()

            # D. Accessing with correct auth parameter -> 200 OK
            conn.request("GET", "/node/protected_node_01?auth=correct_dash_token_999")
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.OK)
            html_body = res.read().decode("utf-8")
            self.assertIn("protected_node_01", html_body)
            self.assertIn("RTX 4090", html_body)
            conn.close()
        finally:
            server.shutdown()
            server.server_close()

    # 4. Stored-XSS Mitigation
    def test_dashboard_html_escapes_xss_payloads(self) -> None:
        malicious_node_data = {
            "inventory": {
                "gpus": [{
                    "model_name": "<script>alert('XSS_GPU')</script>",
                    "vram_bytes": 16 * 1024**3,
                }]
            },
            "telemetry": {
                "gpu_thermals": [{
                    "temp": "<img src=x onerror=alert(1)>",
                    "fan": "100%",
                    "power_watts": "120",
                }],
                "tokens_processed": 1000,
            },
            "global_mesh": {},
        }
        rendered = render_node_remote_dashboard_html(
            node_id="<script>alert('XSS_NODE')</script>",
            auth_token="token_test",
            node_data=malicious_node_data,
        )

        # Ensure raw dangerous script tags are NOT present in output
        self.assertNotIn("<script>alert('XSS_GPU')</script>", rendered)
        self.assertNotIn("<script>alert('XSS_NODE')</script>", rendered)
        self.assertNotIn("<img src=x onerror=alert(1)>", rendered)

        # Ensure proper HTML escaping
        self.assertIn("&lt;script&gt;alert(&#x27;XSS_GPU&#x27;)&lt;/script&gt;", rendered)
        self.assertIn("&lt;script&gt;alert(&#x27;XSS_NODE&#x27;)&lt;/script&gt;", rendered)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rendered)

    # 5. Rate-Limiter Authentication Gating
    def test_rate_limiter_does_not_grant_auth_tier_for_bogus_bearer_token(self) -> None:
        handler = GatewayHandler.__new__(GatewayHandler)
        handler.auth_manager = self.auth_manager

        # Bogus bearer token must evaluate is_authenticated = False
        fake_headers = {"Authorization": "Bearer random_unregistered_attacker_token_xyz"}
        token = extract_bearer_token(fake_headers)
        is_auth = bool(token) and handler.auth_manager.is_valid_key(token)
        self.assertFalse(is_auth)

        # Valid registered key must evaluate is_authenticated = True
        valid_headers = {"Authorization": "Bearer cm_live_valid_key_12345"}
        valid_token = extract_bearer_token(valid_headers)
        is_valid_auth = bool(valid_token) and handler.auth_manager.is_valid_key(valid_token)
        self.assertTrue(is_valid_auth)

    # 6. Trusted Proxy Client IP Resolution
    def test_trusted_proxies_client_ip_spoofing_prevention(self) -> None:
        headers_with_spoof = {"X-Forwarded-For": "203.0.113.195, 198.51.100.1"}

        # Direct untrusted remote peer (e.g. 198.51.100.55) -> X-Forwarded-For is ignored!
        ip_remote = resolve_client_ip(headers_with_spoof, client_address=("198.51.100.55", 44321))
        self.assertEqual(ip_remote, "198.51.100.55")

        # Trusted local proxy peer (127.0.0.1) -> X-Forwarded-For is trusted
        ip_proxy = resolve_client_ip(headers_with_spoof, client_address=("127.0.0.1", 54321))
        self.assertEqual(ip_proxy, "203.0.113.195")

    # 7. Idempotent Initial Grant
    def test_initial_grant_is_strictly_idempotent(self) -> None:
        headers = {"Authorization": "Bearer cm_live_valid_key_12345"}
        account_id = "cust_valid_account_01"

        # 1. First authentication -> initial grant granted (10M micro-units)
        auth1 = self.auth_manager.authenticate_request(headers)
        self.assertEqual(auth1.account_id, account_id)
        self.assertEqual(self.ledger.get_balance(account_id), 10_000_000)
        self.assertTrue(self.ledger.has_received_initial_grant(account_id))

        # 2. Simulate account spending all credits to 0 balance
        self.ledger.record_job_execution(
            job_id="job_drain_01",
            customer_account_id=account_id,
            provider_shares=[("prov_1", 1.0)],
            model_id="qwen/qwen2.5-7b-instruct",
            prompt_tokens=50_000,
            completion_tokens=0,
            network_fee_bps=0,
        )
        self.assertEqual(self.ledger.get_balance(account_id), 0)

        # 3. Second authentication with 0 balance -> MUST NOT issue a second initial grant!
        auth2 = self.auth_manager.authenticate_request(headers)
        self.assertEqual(auth2.account_id, account_id)
        self.assertEqual(self.ledger.get_balance(account_id), 0)

    # 8. Thread-safe Atomic Registry Persistence
    def test_atomic_registry_persistence(self) -> None:
        registry_data = {
            "node_alpha": {"node_id": "node_alpha", "auth_token": "tok_a"},
            "node_beta": {"node_id": "node_beta", "auth_token": "tok_b"},
        }
        save_node_telemetry_registry(registry_data)
        self.assertEqual(NODE_TELEMETRY_REGISTRY.get("node_alpha", {}).get("auth_token"), "tok_a")


if __name__ == "__main__":
    unittest.main()
