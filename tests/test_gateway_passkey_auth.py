"""HTTP-level tests for passkey auth routes served by the live gateway process
(GatewayHandler) -- production nginx routes all /api/* traffic here, not to
services.portal.server_core.PortalHandler, so this is the path that matters.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

import services.gateway.server as gateway_server_module
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
from services.billing.owner_accounts import OwnerAccountStore
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore


class TestGatewayPasskeyAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()

        self.original_owner_store = gateway_server_module.OWNER_ACCOUNT_STORE
        self.owner_store = OwnerAccountStore(Path(self.tmp_dir.name) / "owners.db")
        gateway_server_module.OWNER_ACCOUNT_STORE = self.owner_store

        self.original_fleet_store = passkey_routes.FLEET_ACCOUNT_STORE
        self.fleet_store = FleetAccountStore(Path(self.tmp_dir.name) / "fleet.db")
        passkey_routes.FLEET_ACCOUNT_STORE = self.fleet_store

        NODE_TELEMETRY_REGISTRY.clear()

        self.server, self.port = gateway_server_module.create_gateway_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.15)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        gateway_server_module.OWNER_ACCOUNT_STORE = self.original_owner_store
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        NODE_TELEMETRY_REGISTRY.clear()
        self.tmp_dir.cleanup()

    def _post(self, path: str, body: dict, cookie: str | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(data))}
        if cookie:
            headers["Cookie"] = cookie
        conn.request("POST", path, body=data, headers=headers)
        res = conn.getresponse()
        payload = json.loads(res.read().decode("utf-8"))
        set_cookie = res.getheader("Set-Cookie")
        conn.close()
        return res.status, payload, set_cookie

    def _get(self, path: str, cookie: str | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Cookie": cookie} if cookie else {}
        conn.request("GET", path, headers=headers)
        res = conn.getresponse()
        payload = json.loads(res.read().decode("utf-8"))
        conn.close()
        return res.status, payload

    def test_me_requires_session(self) -> None:
        status, data = self._get("/api/auth/me")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_portal_fleet_requires_session(self) -> None:
        status, data = self._get("/api/portal/fleet")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_register_begin_for_new_email(self) -> None:
        status, data, cookie = self._post("/api/auth/register/begin", {"email": "new@example.com"})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("options", data)
        self.assertIsNone(cookie)

    def test_login_begin_unknown_email(self) -> None:
        status, data, cookie = self._post("/api/auth/login/begin", {"email": "ghost@example.com"})
        self.assertEqual(status, HTTPStatus.NOT_FOUND)

    def test_me_and_portal_fleet_via_session_cookie(self) -> None:
        account = self.fleet_store.create_account("owner@example.com")
        token = self.fleet_store.create_session(account.account_id)
        cookie = f"{passkey_routes.SESSION_COOKIE_NAME}={token}"

        status, me = self._get("/api/auth/me", cookie=cookie)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(me["owner_key"], account.owner_key)

        owner_id = gateway_server_module.owner_id_for_key(account.owner_key)
        self.owner_store.ensure_owner(owner_id)
        self.owner_store.bind_provider_node(owner_id, "rig-live")
        NODE_TELEMETRY_REGISTRY["rig-live"] = {
            "node_id": "rig-live",
            "auth_token": "cm_tunnel_deadbeef",
            "inventory": {"gpus": [{"model_name": "RTX 4090", "vram_bytes": 24 * 1024**3, "vendor": "nvidia"}]},
            "telemetry": {"local_compute_tflops": 60.0},
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        status, fleet = self._get("/api/portal/fleet", cookie=cookie)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(fleet["total_nodes_bound"], 1)
        self.assertEqual(fleet["total_nodes_online"], 1)
        self.assertEqual(fleet["nodes"][0]["remote_url"], "/node/rig-live?auth=cm_tunnel_deadbeef")

    def test_logout_clears_cookie_session(self) -> None:
        account = self.fleet_store.create_account("owner2@example.com")
        token = self.fleet_store.create_session(account.account_id)
        cookie = f"{passkey_routes.SESSION_COOKIE_NAME}={token}"

        status, data, _ = self._post("/api/auth/logout", {}, cookie=cookie)
        self.assertEqual(status, HTTPStatus.OK)

        status, _ = self._get("/api/auth/me", cookie=cookie)
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)


if __name__ == "__main__":
    unittest.main()
