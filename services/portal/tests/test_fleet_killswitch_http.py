# SPDX-License-Identifier: Apache-2.0
"""HTTP tests for multi-tenant Kill Switch portal endpoints and Master authorization scoping."""
from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.portal.server import PortalHandler
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore
import services.gateway.server as gateway_server_module
from services.billing.owner_accounts import OwnerAccountStore
from runtime.safety.dead_mans_switch import (
    DeadMansLeaseGuard,
    ExecutionLease,
    get_lease_guard,
    set_global_lease_guard,
    utc_now,
)

PORT = 13038
BASE = f"http://127.0.0.1:{PORT}"


class TestFleetKillswitchHttp(unittest.TestCase):
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

        # Fresh DeadMansLeaseGuard
        self.guard = DeadMansLeaseGuard(node_id="test-portal-node", default_ttl_seconds=20.0)
        set_global_lease_guard(self.guard)

        # Issue active lease
        now = utc_now()
        active_lease = ExecutionLease(
            lease_id="portal-test-lease",
            node_id="test-portal-node",
            issued_at_iso=now.isoformat().replace("+00:00", "Z"),
            expires_at_iso=(now + datetime.resolution * 20000000).isoformat().replace("+00:00", "Z"),
            ttl_seconds=20.0,
        )
        self.guard.update_lease(active_lease, verify_signature=False)

        # Create test fleet account
        self.account = self.fleet_store.create_account("provider@test.com")
        self.owner_store.ensure_owner(self.account.account_id)

        # Set master admin key env
        os.environ["COMPUTEMESH_MASTER_ADMIN_KEY"] = "master_secret_stripe_inetconnector_key"

    def tearDown(self) -> None:
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        gateway_server_module.OWNER_ACCOUNT_STORE = self.original_owner_store
        self.guard.reset()
        self.tmp_dir.cleanup()
        os.environ.pop("COMPUTEMESH_MASTER_ADMIN_KEY", None)

    def _post(self, path: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(f"{BASE}{path}", data=data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return exc.code, json.loads(raw) if raw else {}

    def _get(self, path: str, headers: dict | None = None) -> tuple[int, dict]:
        req_headers = {}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(f"{BASE}{path}", headers=req_headers, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            return exc.code, json.loads(raw) if raw else {}

    def test_fleet_scoped_kill_switch_success(self) -> None:
        expected_owner = gateway_server_module.owner_id_for_key(self.account.owner_key)
        # Provider trips fleet
        status, res = self._post(
            "/api/portal/fleet/killswitch/trigger",
            {"scope": "fleet", "reason": "GPU Maintenance"},
            headers={"X-Owner-Key": self.account.owner_key},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["scope"], "fleet")
        self.assertEqual(res["owner_id"], expected_owner)

        # Verify fleet is tripped in guard
        self.assertTrue(self.guard.is_fleet_tripped(expected_owner))
        # Global platform is NOT tripped
        self.assertFalse(self.guard.is_tripped)

        # GET status returns fleet_status with is_tripped = True
        g_status, g_res = self._get(
            "/api/portal/fleet/killswitch/status",
            headers={"X-Owner-Key": self.account.owner_key},
        )
        self.assertEqual(g_status, HTTPStatus.OK)
        self.assertTrue(g_res["fleet_status"]["is_tripped"])
        self.assertFalse(g_res["is_tripped"])

        # Reset fleet
        r_status, r_res = self._post(
            "/api/portal/fleet/killswitch/reset",
            {"scope": "fleet", "reason": "GPU Maintenance Complete"},
            headers={"X-Owner-Key": self.account.owner_key},
        )
        self.assertEqual(r_status, HTTPStatus.OK)
        self.assertFalse(self.guard.is_fleet_tripped(expected_owner))

    def test_non_master_fleet_operator_cannot_trip_global_platform(self) -> None:
        expected_owner = gateway_server_module.owner_id_for_key(self.account.owner_key)
        # A normal fleet operator tries scope='global'
        status, res = self._post(
            "/api/portal/fleet/killswitch/trigger",
            {"scope": "global", "reason": "Malicious or accidental platform shutdown attempt"},
            headers={"X-Owner-Key": self.account.owner_key},
        )
        # Must be rejected with 403 Forbidden
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertEqual(res["status"], "forbidden")
        self.assertIn("Berechtigungs-Schutz", res["error"])

        # Global platform remains 100% operational
        self.assertFalse(self.guard.is_tripped)

        # But their own fleet was safely isolated and stopped
        self.assertTrue(self.guard.is_fleet_tripped(expected_owner))

    def test_master_admin_can_trip_global_platform(self) -> None:
        # Master platform owner provides valid X-Master-Killswitch-Key
        status, res = self._post(
            "/api/portal/fleet/killswitch/trigger",
            {"scope": "global", "reason": "Platform emergency maintenance"},
            headers={"X-Master-Killswitch-Key": "master_secret_stripe_inetconnector_key"},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(res["status"], "global_tripped")
        self.assertTrue(self.guard.is_tripped)

        # Master resets global platform
        r_status, r_res = self._post(
            "/api/portal/fleet/killswitch/reset",
            {"scope": "global", "reason": "Platform restored"},
            headers={"X-Master-Killswitch-Key": "master_secret_stripe_inetconnector_key"},
        )
        self.assertEqual(r_status, HTTPStatus.OK)
        self.assertFalse(self.guard.is_tripped)


if __name__ == "__main__":
    unittest.main()
