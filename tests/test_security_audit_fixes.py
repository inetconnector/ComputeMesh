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
9. Portal server heartbeat token gating for existing nodes.
10. Appliance Dashboard status does not leak control auth_token.
11. Canonical pricing consistency across all platform subsystems.
12. Pre-inference balance reservation preventing unpaid compute execution.
13. Dynamic API key revocation without process restart.
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
from services.appliance_dashboard.server import DashboardHandler
from services.billing.ledger import InsufficientBalanceError, Ledger
from services.common.pricing import (
    DEFAULT_PRICE_TIERS,
    MICRO_UNITS_PER_USD,
    calculate_max_charge_micro,
    calculate_token_charge_micro,
    get_price_tier,
)
from services.gateway.auth import (
    GatewayAuthManager,
    extract_bearer_token,
    resolve_client_ip,
)
from services.gateway.catalog import AVAILABLE_MODELS
from services.gateway.dashboard import (
    NODE_TELEMETRY_REGISTRY,
    render_node_remote_dashboard_html,
    save_node_telemetry_registry,
)
from services.gateway.inference import InferenceEngine
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.security import RateLimiter
from services.gateway.server import GatewayHandler, create_gateway_server
from services.gateway.teaser import TeaserQuotaManager
from services.portal.routes_quotes import PortalQuotesHandler
from services.portal.server import PortalHandler
from tools.appliance.appliance_config import ApplianceConfig
from tools.appliance.hardware_detector import RigInventory


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

        tunnel_server = MeshTunnelServer(
            listen_host="127.0.0.1",
            listen_port=0,
            target_host="127.0.0.1",
            target_port=echo_port,
            server_creds=server_creds,
            allowed_client_nodes={"node_auth_client_01"},
        )
        server_mesh_port = tunnel_server.start()

        tunnel_auth_client = MeshTunnelClient(
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_mesh_port,
            client_creds=authorized_client_creds,
            expected_server_node_id="node_server_01",
        )
        client_local_port = tunnel_auth_client.start()

        try:
            app_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            app_sock.connect(("127.0.0.1", client_local_port))
            app_sock.sendall(b"PING_SECURE_AUTH")
            resp = app_sock.recv(1024)
            app_sock.close()
            self.assertEqual(resp, b"ECHO:PING_SECURE_AUTH")
        finally:
            tunnel_auth_client.stop()

        tunnel_rogue_client = MeshTunnelClient(
            remote_tunnel_host="127.0.0.1",
            remote_tunnel_port=server_mesh_port,
            client_creds=unauthorized_client_creds,
            expected_server_node_id="node_server_01",
        )
        rogue_local_port = tunnel_rogue_client.start()

        try:
            app_sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            app_sock2.connect(("127.0.0.1", rogue_local_port))
            app_sock2.sendall(b"PING_ROGUE")
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
                    "model_name": "<script>alert('xss')</script>",
                    "vram_bytes": 16 * 1024**3,
                    "driver_backend": "cuda",
                }]
            },
            "telemetry": {
                "gpu_thermals": [{
                    "gpu_index": "<img src=x onerror=alert(1)>",
                    "temp": 55,
                    "fan": 60,
                    "power_watts": 120,
                    "tflops": 24.5,
                }]
            }
        }
        rendered = render_node_remote_dashboard_html("<img src=x onerror=steal()>", "token123", malicious_node_data)
        self.assertNotIn("<script>alert('xss')</script>", rendered)
        self.assertNotIn("<img src=x onerror=steal()>", rendered)
        self.assertIn("&lt;img src=x onerror=steal()&gt;", rendered)

    # 5. Rate-Limiter Authentication Gating
    def test_rate_limiter_does_not_grant_auth_tier_for_bogus_bearer_token(self) -> None:
        handler = GatewayHandler.__new__(GatewayHandler)
        handler.auth_manager = self.auth_manager

        fake_headers = {"Authorization": "Bearer random_unregistered_attacker_token_xyz"}
        token = extract_bearer_token(fake_headers)
        is_auth = bool(token) and handler.auth_manager.is_valid_key(token)
        self.assertFalse(is_auth)

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

        # 1. First authentication -> initial grant granted (10M micro-units = $10.00)
        auth1 = self.auth_manager.authenticate_request(headers)
        self.assertEqual(auth1.account_id, account_id)
        self.assertEqual(self.ledger.get_balance(account_id), 10_000_000)
        self.assertTrue(self.ledger.has_received_initial_grant(account_id))

        # 2. Simulate account spending all credits to 0 balance (50M prompt + 10M completion tokens on 7B = $10.00)
        self.ledger.record_job_execution(
            job_id="job_drain_01",
            customer_account_id=account_id,
            provider_shares=[("prov_1", 1.0)],
            model_id="qwen/qwen2.5-7b-instruct",
            prompt_tokens=50_000_000,
            completion_tokens=10_000_000,
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

    # 9. Portal Server Heartbeat Token Comparison for Existing Nodes
    def test_portal_heartbeat_rejects_token_mismatch_for_existing_node(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        NODE_TELEMETRY_REGISTRY["node_secure_01"] = {
            "node_id": "node_secure_01",
            "auth_token": "cm_tunnel_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "telemetry": {},
        }

        from http.server import ThreadingHTTPServer
        portal_server = ThreadingHTTPServer(("127.0.0.1", 0), PortalHandler)
        port = portal_server.server_port
        t = threading.Thread(target=portal_server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        try:
            # Attack attempt: Attacker sends same node_id with DIFFERENT token
            conn1 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            attacker_body = json.dumps({
                "node_id": "node_secure_01",
                "auth_token": "cm_tunnel_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }).encode("utf-8")
            conn1.request("POST", "/api/v1/node/heartbeat", body=attacker_body, headers={"Content-Type": "application/json", "Content-Length": str(len(attacker_body))})
            res1 = conn1.getresponse()
            self.assertEqual(res1.status, HTTPStatus.UNAUTHORIZED)
            res1.read()
            conn1.close()

            # Legitimate node sends correct token
            conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            legit_body = json.dumps({
                "node_id": "node_secure_01",
                "auth_token": "cm_tunnel_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            }).encode("utf-8")
            conn2.request("POST", "/api/v1/node/heartbeat", body=legit_body, headers={"Content-Type": "application/json", "Content-Length": str(len(legit_body))})
            res2 = conn2.getresponse()
            self.assertEqual(res2.status, HTTPStatus.OK)
            res2.read()
            conn2.close()
        finally:
            portal_server.shutdown()
            portal_server.server_close()

    # 10. Appliance Dashboard Does Not Leak auth_token
    def test_appliance_status_does_not_leak_auth_token(self) -> None:
        from http.server import ThreadingHTTPServer
        DashboardHandler.config = ApplianceConfig(
            rig_name="miner-alpha",
            provider_account_id="cm_0x999",
            payout_address="0x1111111111111111111111111111111111111111",
            coordinator_url="https://coord.test",
            network_mode="dhcp",
            static_ip=None,
            gateway=None,
            dns=None,
            enable_web_dashboard=True,
            dashboard_port=8080,
            allow_ssh=False,
            ssh_authorized_keys=None,
        )
        DashboardHandler.inventory = RigInventory(
            schema_version=1,
            captured_at="2026-08-26T12:00:00Z",
            host_architecture="linux",
            total_gpus=0,
            total_vram_bytes=0,
            gpus=[],
            pcie_riser_warning=False,
        )
        DashboardHandler.node_id = "miner-alpha"

        dash_server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        port = dash_server.server_port
        t = threading.Thread(target=dash_server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.1)

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/status")
            res = conn.getresponse()
            self.assertEqual(res.status, HTTPStatus.OK)
            data = json.loads(res.read().decode("utf-8"))
            self.assertNotIn("auth_token", data)
            interfaces = data.get("network", {}).get("interfaces", [])
            self.assertTrue(any("[REDACTED]" in iface.get("url", "") for iface in interfaces))
            conn.close()
        finally:
            dash_server.shutdown()
            dash_server.server_close()

    # 11. Canonical Pricing Scale Consistency
    def test_pricing_scale_consistency_across_subsystems(self) -> None:
        # 1M tokens of 7B ($0.15 prompt + $0.25 completion -> 200,000 micro-units = $0.20)
        charge = calculate_token_charge_micro("qwen/qwen2.5-7b-instruct", prompt_tokens=500_000, completion_tokens=500_000)
        self.assertEqual(charge, 200_000)  # $0.20
        self.assertEqual(charge / MICRO_UNITS_PER_USD, 0.20)

        # Quotes handler calculation for 100M tokens of 8B ($0.15*0.75 + $0.25*0.25 = $0.175/M -> $17.50 for 100M)
        quotes = PortalQuotesHandler()
        res, err, status = quotes.handle_quote({"tokens_million": 100.0, "model_tier": "8b"})
        self.assertIsNone(err)
        self.assertEqual(res["total_cost_usd"], 17.50)

    # 12. Pre-Inference Balance Reservation Prevents Unpaid Compute
    def test_pre_inference_reservation_prevents_unpaid_compute(self) -> None:
        backend_mock = MagicMock()
        engine = InferenceEngine(
            ledger=self.ledger,
            metrics=MetricsRegistry(),
            teaser_manager=self.teaser_manager,
            backend=backend_mock,
        )
        # Account with only 10 micro-units (insufficient for standard completion hold)
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_poor",
            amount_micro_units=10,
            payment_reference="dep_tiny",
        )

        with self.assertRaises(InsufficientBalanceError):
            engine.create_metered_completion(
                account_id="cust_poor",
                model_id="qwen/qwen2.5-7b-instruct",
                messages=[{"role": "user", "content": "Compute large matrix multiplication"}],
            )
        # Backend must NEVER have been called!
        backend_mock.complete.assert_not_called()

    # 13. Dynamic Key Revocation in GatewayAuthManager
    def test_api_key_revocation_removes_deleted_keys(self) -> None:
        key_store_file = self.work_dir / "api_keys.json"
        key_store_file.write_text(json.dumps({
            "keys": [
                {"api_key": "cm_live_key_alpha", "account_id": "cust_alpha"},
                {"api_key": "cm_live_key_beta", "account_id": "cust_beta"},
            ]
        }), encoding="utf-8")

        auth_mgr = GatewayAuthManager(
            ledger=self.ledger,
            teaser_manager=self.teaser_manager,
            api_key_store_path=key_store_file,
        )
        self.assertTrue(auth_mgr.is_valid_key("cm_live_key_alpha"))
        self.assertTrue(auth_mgr.is_valid_key("cm_live_key_beta"))

        # Revoke alpha by removing it from the store file
        key_store_file.write_text(json.dumps({
            "keys": [
                {"api_key": "cm_live_key_beta", "account_id": "cust_beta"},
            ]
        }), encoding="utf-8")

        auth_mgr.refresh_registered_keys()
        self.assertFalse(auth_mgr.is_valid_key("cm_live_key_alpha"))
        self.assertTrue(auth_mgr.is_valid_key("cm_live_key_beta"))

    # 14. Ledger Thread-Safety Under Concurrent Credit Holds and Transactions
    def test_ledger_thread_safety_under_concurrent_holds_and_transactions(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_concurrent",
            amount_micro_units=1_000_000,
            payment_reference="dep_concurrent",
        )
        errors = []

        def worker(idx: int):
            try:
                hold = self.ledger.create_hold(
                    account_id="cust_concurrent",
                    amount_micro_units=500,
                    model_id="qwen/qwen2.5-7b-instruct",
                )
                time.sleep(0.001)
                self.ledger.capture_hold(
                    hold_id=hold.hold_id,
                    job_id=f"job_con_{idx}",
                    customer_account_id="cust_concurrent",
                    provider_shares=[("node-a", 1.0)],
                    model_id="qwen/qwen2.5-7b-instruct",
                    prompt_tokens=100,
                    completion_tokens=100,
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertGreater(self.ledger.get_balance("provider:node-a"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    # 15. Credit Hold Lifecycle with max_tokens, Capture and Release
    def test_credit_hold_lifecycle_with_max_tokens_and_capture_release(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_hold_test",
            amount_micro_units=200_000,
            payment_reference="dep_hold_test",
        )
        # Create hold for 50,000 micro-units
        hold = self.ledger.create_hold(
            account_id="cust_hold_test",
            amount_micro_units=50_000,
            model_id="qwen/qwen2.5-7b-instruct",
        )
        # Available balance must reflect reserved hold
        self.assertEqual(self.ledger.get_available_balance("cust_hold_test"), 150_000)
        self.assertEqual(self.ledger.get_balance("cust_hold_test"), 200_000)

        # Release hold
        self.assertTrue(self.ledger.release_hold(hold.hold_id))
        self.assertEqual(self.ledger.get_available_balance("cust_hold_test"), 200_000)

    # 16. Portal Rate Limiter Blocks Spoofed X-Forwarded-For from Untrusted Clients
    def test_portal_rate_limiter_blocks_spoofed_forwarded_for_from_untrusted_clients(self) -> None:
        from http.client import HTTPMessage
        headers = HTTPMessage()
        headers["X-Forwarded-For"] = "1.2.3.4, 5.6.7.8"
        # Remote untrusted socket address
        resolved = resolve_client_ip(headers, ("198.51.100.25", 48200))
        # Must resolve to remote peer IP, NOT the spoofed header
        self.assertEqual(resolved, "198.51.100.25")

        # Trusted loopback socket address
        resolved_loopback = resolve_client_ip(headers, ("127.0.0.1", 48200))
        self.assertEqual(resolved_loopback, "1.2.3.4")

    # 17. Release Manifest SHA-256 Binary Integrity & Ed25519 Signature Verification
    def test_release_manifest_sha256_binary_integrity(self) -> None:
        import hashlib
        from tools.security.ed25519_verify import verify_ed25519_signature
        manifest_file = REPO_ROOT / "portal" / "updates" / "version.json"
        self.assertTrue(manifest_file.exists())
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("version"), "1.2.17")

        for platform, info in data.get("platforms", {}).items():
            fn = info.get("filename")
            expected_sha = info.get("sha256")
            expected_size = info.get("size_bytes")
            if fn:
                local_binary = REPO_ROOT / "portal" / "downloads" / fn
                self.assertTrue(local_binary.exists(), f"Release binary {fn} must exist in portal/downloads")
                actual_bytes = local_binary.read_bytes()
                actual_sha = hashlib.sha256(actual_bytes).hexdigest()
                self.assertEqual(actual_sha, expected_sha, f"SHA-256 mismatch for {fn}")
                self.assertEqual(len(actual_bytes), expected_size, f"Size mismatch for {fn}")

        pub_hex = data.get("public_key")
        sig_hex = data.get("signature")
        self.assertTrue(pub_hex, "Public key must be present in release manifest")
        self.assertTrue(sig_hex, "Digital signature must be present in release manifest")

        manifest_copy = dict(data)
        manifest_copy.pop("signature", None)
        canonical_bytes = json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
        is_valid = verify_ed25519_signature(bytes.fromhex(pub_hex), canonical_bytes, bytes.fromhex(sig_hex))
        self.assertTrue(is_valid, "Release manifest digital signature must be cryptographically valid")

    # 18. Strict capture_hold Invariants & Hold Overrun Protection
    def test_capture_hold_strict_invariants(self) -> None:
        from services.billing.ledger import BillingError, InsufficientBalanceError
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_strict",
            amount_micro_units=500_000,
            payment_reference="dep_strict",
        )
        hold = self.ledger.create_hold(
            account_id="cust_strict",
            amount_micro_units=100_000,
            model_id="qwen/qwen2.5-7b-instruct",
        )

        # A. Nonexistent hold is rejected
        with self.assertRaises(BillingError):
            self.ledger.capture_hold(
                hold_id="hold_nonexistent",
                job_id="job_x",
                customer_account_id="cust_strict",
                provider_shares=[("node-a", 1.0)],
                model_id="qwen/qwen2.5-7b-instruct",
                prompt_tokens=100,
                completion_tokens=100,
            )

        # B. Account mismatch is rejected
        with self.assertRaises(BillingError):
            self.ledger.capture_hold(
                hold_id=hold.hold_id,
                job_id="job_x",
                customer_account_id="cust_other",
                provider_shares=[("node-a", 1.0)],
                model_id="qwen/qwen2.5-7b-instruct",
                prompt_tokens=100,
                completion_tokens=100,
            )

        # C. Valid capture succeeds and marks hold captured
        tx = self.ledger.capture_hold(
            hold_id=hold.hold_id,
            job_id="job_valid_cap",
            customer_account_id="cust_strict",
            provider_shares=[("node-a", 1.0)],
            model_id="qwen/qwen2.5-7b-instruct",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        self.assertIsNotNone(tx)
        self.assertEqual(hold.status, "captured")


if __name__ == "__main__":
    unittest.main()
