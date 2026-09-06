"""HTTP-level tests for the /fleet page and its session-authenticated APIs."""
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from services.portal.server import PortalHandler
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
import services.gateway.server as gateway_server_module
from services.billing.owner_accounts import OwnerAccountStore

PORT = 13020
BASE = f"http://127.0.0.1:{PORT}"


class TestFleetHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", PORT), PortalHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.original_fleet_store = passkey_routes.FLEET_ACCOUNT_STORE
        self.fleet_store = FleetAccountStore(Path(self.tmp_dir.name) / "fleet.db")
        passkey_routes.FLEET_ACCOUNT_STORE = self.fleet_store

        self.original_owner_store = gateway_server_module.OWNER_ACCOUNT_STORE
        self.owner_store = OwnerAccountStore(Path(self.tmp_dir.name) / "owners.db")
        gateway_server_module.OWNER_ACCOUNT_STORE = self.owner_store

        NODE_TELEMETRY_REGISTRY.clear()

    def tearDown(self) -> None:
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        gateway_server_module.OWNER_ACCOUNT_STORE = self.original_owner_store
        NODE_TELEMETRY_REGISTRY.clear()
        self.tmp_dir.cleanup()

    def _post(self, path: str, body: dict, cookie: str | None = None, headers: dict | None = None):
        data = json.dumps(body).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(
            f"{BASE}{path}", data=data, method="POST", headers=req_headers
        )
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers.get("Set-Cookie")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), None

    def _get(self, path: str, cookie: str | None = None, headers: dict | None = None):
        req = urllib.request.Request(f"{BASE}{path}")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, resp
        except urllib.error.HTTPError as exc:
            return exc.code, exc

    def test_fleet_page_served(self) -> None:
        status, resp = self._get("/fleet")
        self.assertEqual(status, 200)
        content = resp.read().decode("utf-8")
        self.assertIn("Passkey", content)

    def test_me_requires_session(self) -> None:
        status, resp = self._get("/api/auth/me")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_portal_fleet_requires_session(self) -> None:
        status, resp = self._get("/api/portal/fleet")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_register_begin_for_new_email(self) -> None:
        status, data, _ = self._post("/api/auth/register/begin", {"email": "new-user@example.com"})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("options", data)

    def test_login_begin_for_unknown_email(self) -> None:
        status, data, _ = self._post("/api/auth/login/begin", {"email": "ghost@example.com"})
        self.assertEqual(status, HTTPStatus.NOT_FOUND)

    def test_me_and_portal_fleet_with_valid_session(self) -> None:
        account = self.fleet_store.create_account("owner@example.com")
        token = self.fleet_store.create_session(account.account_id)
        cookie = f"{passkey_routes.SESSION_COOKIE_NAME}={token}"

        status, resp = self._get("/api/auth/me", cookie=cookie)
        self.assertEqual(status, HTTPStatus.OK)
        me = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(me["email"], "owner@example.com")
        self.assertEqual(me["owner_key"], account.owner_key)

        owner_id = gateway_server_module.owner_id_for_key(account.owner_key)
        self.owner_store.ensure_owner(owner_id)
        self.owner_store.bind_provider_node(owner_id, "rig-01")
        NODE_TELEMETRY_REGISTRY["rig-01"] = {
            "node_id": "rig-01",
            "auth_token": "cm_tunnel_abc123",
            "inventory": {"gpus": [{"model_name": "RTX 3080", "vram_bytes": 10 * 1024**3, "vendor": "nvidia"}]},
            "telemetry": {"local_compute_tflops": 20.0},
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        status, resp = self._get("/api/portal/fleet", cookie=cookie)
        self.assertEqual(status, HTTPStatus.OK)
        fleet = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(fleet["total_nodes_bound"], 1)
        self.assertEqual(fleet["total_nodes_online"], 1)
        self.assertEqual(fleet["nodes"][0]["node_id"], "rig-01")
        self.assertEqual(fleet["nodes"][0]["remote_url"], "/node/rig-01?auth=cm_tunnel_abc123")

    def test_portal_fleet_with_direct_owner_key_header_and_query(self) -> None:
        owner_key = "cm_owner_direct_test_key_123"
        owner_id = gateway_server_module.owner_id_for_key(owner_key)
        self.owner_store.ensure_owner(owner_id)
        self.owner_store.bind_provider_node(owner_id, "node-direct-01")
        NODE_TELEMETRY_REGISTRY["node-direct-01"] = {
            "node_id": "node-direct-01",
            "auth_token": "cm_tunnel_direct_456",
            "inventory": {"gpus": [{"model_name": "RTX 4090", "vram_bytes": 24 * 1024**3, "vendor": "nvidia"}]},
            "telemetry": {"local_compute_tflops": 82.6},
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        # 1. Via Query Parameter
        req = urllib.request.Request(f"{BASE}/api/portal/fleet?owner_key={owner_key}")
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["total_nodes_bound"], 1)
        self.assertEqual(data["nodes"][0]["node_id"], "node-direct-01")
        self.assertEqual(data["nodes"][0]["remote_url"], "/node/node-direct-01?auth=cm_tunnel_direct_456")

        # 2. Via X-Owner-Key Header
        req_hdr = urllib.request.Request(f"{BASE}/api/portal/fleet", headers={"X-Owner-Key": owner_key})
        resp_hdr = urllib.request.urlopen(req_hdr)
        self.assertEqual(resp_hdr.status, HTTPStatus.OK)
        data_hdr = json.loads(resp_hdr.read().decode("utf-8"))
        self.assertEqual(data_hdr["total_nodes_bound"], 1)
        self.assertEqual(data_hdr["nodes"][0]["node_id"], "node-direct-01")

    def test_invalid_session_cookie_rejected(self) -> None:
        status, resp = self._get("/api/auth/me", cookie=f"{passkey_routes.SESSION_COOKIE_NAME}=garbage-token")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_unbind_node_api_removes_from_fleet_and_registry(self) -> None:
        owner_key = "cm_owner_unbind_test_key"
        owner_id = gateway_server_module.owner_id_for_key(owner_key)
        self.owner_store.ensure_owner(owner_id)
        self.owner_store.bind_provider_node(owner_id, "stale-node-01")
        NODE_TELEMETRY_REGISTRY["stale-node-01"] = {
            "node_id": "stale-node-01",
            "auth_token": "cm_tunnel_stale_123",
            "inventory": {"gpus": []},
            "telemetry": {"local_compute_tflops": 0.0},
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        # 1. Missing node_id returns 400
        status, data, _ = self._post("/api/portal/fleet/unbind_node", {"owner_key": owner_key})
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

        # 2. Valid unbind removes from DB and registry
        status, data, _ = self._post(
            "/api/portal/fleet/unbind_node",
            {"node_id": "stale-node-01", "owner_key": owner_key},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(data.get("unbound"))
        self.assertEqual(data.get("node_id"), "stale-node-01")
        self.assertNotIn("stale-node-01", NODE_TELEMETRY_REGISTRY)
        self.assertEqual(self.owner_store.list_provider_nodes(owner_id), [])

    def test_enrollment_token_with_owner_key_header(self) -> None:
        owner_key = "cm_owner_enroll_test_999"
        req = urllib.request.Request(
            f"{BASE}/api/portal/fleet/enrollment_token",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-Owner-Key": owner_key},
            method="POST",
        )
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("enrollment_token", data)
        self.assertTrue(data["enrollment_token"].startswith("cmenroll_"))

    def test_stale_and_offline_nodes_are_filtered_from_vram_aggregation(self) -> None:
        owner_key = "cm_owner_telemetry_test_key"
        owner_id = gateway_server_module.owner_id_for_key(owner_key)
        self.owner_store.ensure_owner(owner_id)
        # Bind 2 nodes to this owner
        self.owner_store.bind_provider_node(owner_id, "node-live-mifcom")
        self.owner_store.bind_provider_node(owner_id, "node-stale-custom")

        # 1. Live node: fresh heartbeat with RTX 3080 16GB
        NODE_TELEMETRY_REGISTRY["node-live-mifcom"] = {
            "node_id": "node-live-mifcom",
            "auth_token": "tok_live",
            "inventory": {"gpus": [{"model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "vendor": "nvidia"}]},
            "telemetry": {"local_compute_tflops": 24.0},
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        # 2. Stale node: heartbeat from 5 minutes ago (offline)
        NODE_TELEMETRY_REGISTRY["node-stale-custom"] = {
            "node_id": "node-stale-custom",
            "auth_token": "tok_stale",
            "inventory": {"gpus": [{"model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "vendor": "nvidia"}]},
            "telemetry": {"local_compute_tflops": 24.0},
            "updated_at": "2026-01-01T00:00:00Z",
        }

        req = urllib.request.Request(f"{BASE}/api/portal/fleet", headers={"X-Owner-Key": owner_key})
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        fleet = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(fleet["total_nodes_bound"], 2)
        self.assertEqual(fleet["total_nodes_online"], 1)
        self.assertEqual(fleet["total_vram_gb"], 16.0)
        self.assertEqual(fleet["total_tflops"], 24.0)

        # Check individual nodes
        live_entry = next(n for n in fleet["nodes"] if n["node_id"] == "node-live-mifcom")
        stale_entry = next(n for n in fleet["nodes"] if n["node_id"] == "node-stale-custom")

        self.assertEqual(live_entry["status"], "online")
        self.assertTrue(live_entry["is_online"])
        self.assertEqual(live_entry["vram_gb"], 16.0)
        self.assertEqual(live_entry["tflops"], 24.0)

        self.assertEqual(stale_entry["status"], "offline")
        self.assertFalse(stale_entry["is_online"])
        self.assertEqual(stale_entry["tflops"], 0.0)

    def test_download_ollama_starter_and_reset_endpoints(self) -> None:
        owner_key = "cm_owner_download_test_key_xyz"
        # 1. Download Windows Starter
        req = urllib.request.Request(f"{BASE}/api/portal/download/ollama-starter?os=windows&key={owner_key}")
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))
        self.assertIn("OLLAMA-MESH-START.bat", resp.headers.get("Content-Disposition", ""))
        content = resp.read().decode("utf-8")
        self.assertIn(owner_key, content)
        self.assertIn("OLLAMA_HOST=0.0.0.0:11434", content)

        # 2. Download Linux Starter
        req_sh = urllib.request.Request(f"{BASE}/api/portal/download/ollama-starter?os=linux&key={owner_key}")
        resp_sh = urllib.request.urlopen(req_sh)
        self.assertEqual(resp_sh.status, HTTPStatus.OK)
        self.assertIn("ollama-mesh-start.sh", resp_sh.headers.get("Content-Disposition", ""))
        content_sh = resp_sh.read().decode("utf-8")
        self.assertIn(owner_key, content_sh)
        self.assertIn('export OLLAMA_HOST="0.0.0.0:11434"', content_sh)

        # 3. Download Reset script
        req_res = urllib.request.Request(f"{BASE}/api/portal/download/ollama-reset?os=windows")
        resp_res = urllib.request.urlopen(req_res)
        self.assertEqual(resp_res.status, HTTPStatus.OK)
        self.assertIn("OLLAMA-RESET-DEFAULT.bat", resp_res.headers.get("Content-Disposition", ""))

    def test_update_email_endpoint(self) -> None:
        owner_key = "inet-test-owner-key-email-update-12345"
        # Direct owner key autoprovisions account
        status, resp_me = self._get("/api/auth/me", headers={"X-Owner-Key": owner_key})
        self.assertEqual(status, HTTPStatus.OK)
        data_me = json.loads(resp_me.read().decode("utf-8"))
        self.assertTrue(data_me["email"].endswith(".local"))

        # Update to real email
        status, data, _ = self._post(
            "/api/auth/email/update",
            {"email": "real-fleet-owner@example.com"},
            headers={"X-Owner-Key": owner_key},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["email"], "real-fleet-owner@example.com")

        # Verify /api/auth/me now reflects the new email
        status, resp_me_updated = self._get("/api/auth/me", headers={"X-Owner-Key": owner_key})
        self.assertEqual(status, HTTPStatus.OK)
        data_me_updated = json.loads(resp_me_updated.read().decode("utf-8"))
        self.assertEqual(data_me_updated["email"], "real-fleet-owner@example.com")


if __name__ == "__main__":
    unittest.main()


