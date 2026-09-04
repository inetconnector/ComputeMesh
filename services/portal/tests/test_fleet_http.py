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

    def _post(self, path: str, body: dict, cookie: str | None = None):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{BASE}{path}", data=data, method="POST", headers={"Content-Type": "application/json"}
        )
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers.get("Set-Cookie")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8")), None

    def _get(self, path: str, cookie: str | None = None):
        req = urllib.request.Request(f"{BASE}{path}")
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


if __name__ == "__main__":
    unittest.main()
