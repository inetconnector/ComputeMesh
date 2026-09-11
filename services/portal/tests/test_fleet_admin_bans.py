# SPDX-License-Identifier: Apache-2.0
"""Unit and HTTP tests for Master Administrator fleet banning, deactivation, and reactivation."""
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
from services.billing.ledger import Ledger
from services.gateway.auth import GatewayAuthManager
from services.gateway.teaser import TeaserQuotaManager
from services.gateway.inference import InferenceEngine
from runtime.safety.dead_mans_switch import (
    DeadMansLeaseGuard,
    ExecutionLease,
    EmergencyKillTrippedError,
    set_global_lease_guard,
    utc_now,
)

PORT = 13042
BASE = f"http://127.0.0.1:{PORT}"


class TestFleetAdminBans(unittest.TestCase):
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

        import services.portal.server_core as portal_server_core
        self.original_portal_core_store = getattr(portal_server_core, "FLEET_ACCOUNT_STORE", None)
        portal_server_core.FLEET_ACCOUNT_STORE = self.fleet_store
        self.original_gateway_fleet_store = getattr(gateway_server_module, "FLEET_ACCOUNT_STORE", None)
        gateway_server_module.FLEET_ACCOUNT_STORE = self.fleet_store

        self.original_owner_store = gateway_server_module.OWNER_ACCOUNT_STORE
        self.owner_store = OwnerAccountStore(Path(self.tmp_dir.name) / "owners.db")
        gateway_server_module.OWNER_ACCOUNT_STORE = self.owner_store

        # Fresh DeadMansLeaseGuard
        self.guard = DeadMansLeaseGuard(node_id="test-portal-node", default_ttl_seconds=30.0)
        set_global_lease_guard(self.guard)

        # Active positive authorization lease
        now = utc_now()
        active_lease = ExecutionLease(
            lease_id="ban-test-lease",
            node_id="test-portal-node",
            issued_at_iso=now.isoformat().replace("+00:00", "Z"),
            expires_at_iso=(now + datetime.resolution * 30000000).isoformat().replace("+00:00", "Z"),
            ttl_seconds=30.0,
        )
        self.guard.update_lease(active_lease, verify_signature=False)

        # Accounts for Fleet A and Fleet B
        self.account_a = self.fleet_store.create_account("fleet_a@test.com")
        self.owner_store.ensure_owner(self.account_a.account_id)

        self.account_b = self.fleet_store.create_account("fleet_b@test.com")
        self.owner_store.ensure_owner(self.account_b.account_id)

        os.environ["COMPUTEMESH_MASTER_ADMIN_KEY"] = "master_secret_stripe_inetconnector_key"
        os.environ["COMPUTEMESH_ADMIN_KEY"] = "computemesh_admin_secret_superkey_24chars"

    def tearDown(self) -> None:
        import services.portal.server_core as portal_server_core
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        portal_server_core.FLEET_ACCOUNT_STORE = self.original_portal_core_store
        gateway_server_module.FLEET_ACCOUNT_STORE = self.original_gateway_fleet_store
        gateway_server_module.OWNER_ACCOUNT_STORE = self.original_owner_store
        self.guard.reset()
        self.tmp_dir.cleanup()
        os.environ.pop("COMPUTEMESH_MASTER_ADMIN_KEY", None)
        os.environ.pop("COMPUTEMESH_ADMIN_KEY", None)

    def _post(self, path: str, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(f"{BASE}{path}", data=data, headers=req_headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def _get(self, path: str, headers: dict | None = None) -> tuple[int, dict]:
        req_headers = {}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(f"{BASE}{path}", headers=req_headers)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_fleet_account_store_ban_and_unban_lifecycle(self) -> None:
        # Create session
        token = self.fleet_store.create_session(self.account_a.account_id)
        self.assertIsNotNone(self.fleet_store.get_session_account(token))
        self.assertFalse(self.fleet_store.is_fleet_banned(self.account_a.account_id))

        # Ban fleet
        res = self.fleet_store.ban_fleet(self.account_a.account_id, reason="Policy violation", banned_by="test_admin")
        self.assertEqual(res["status"], "banned")
        self.assertTrue(self.fleet_store.is_fleet_banned(self.account_a.account_id))
        self.assertTrue(self.fleet_store.is_fleet_banned(self.account_a.owner_key))

        # Check in-memory guard was automatically tripped
        self.assertTrue(self.guard.is_fleet_tripped(self.account_a.account_id))
        self.assertFalse(self.guard.is_fleet_tripped(self.account_b.account_id))

        # Check sessions were revoked
        self.assertIsNone(self.fleet_store.get_session_account(token))

        # Check ban info
        info = self.fleet_store.get_fleet_ban_info(self.account_a.account_id)
        self.assertIsNotNone(info)
        self.assertEqual(info["reason"], "Policy violation")

        # Check list banned
        banned_list = self.fleet_store.list_banned_fleets(active_only=True)
        self.assertTrue(any(b["owner_id"] == self.account_a.account_id for b in banned_list))

        # Test persistence across new store instance pointing to same SQLite DB
        reloaded_store = FleetAccountStore(self.fleet_store.storage_path)
        self.assertTrue(reloaded_store.is_fleet_banned(self.account_a.account_id))

        # Unban fleet
        unbanned = self.fleet_store.unban_fleet(self.account_a.account_id, reason="Review cleared", unbanned_by="test_admin")
        self.assertTrue(unbanned)
        self.assertFalse(self.fleet_store.is_fleet_banned(self.account_a.account_id))
        self.assertFalse(self.guard.is_fleet_tripped(self.account_a.account_id))

    def test_owner_account_store_ban_and_unban_lifecycle(self) -> None:
        self.assertFalse(self.owner_store.is_owner_banned(self.account_a.account_id))
        self.owner_store.ban_owner(self.account_a.account_id, reason="Unpaid bill")
        self.assertTrue(self.owner_store.is_owner_banned(self.account_a.account_id))

        # Unban
        self.assertTrue(self.owner_store.unban_owner(self.account_a.account_id))
        self.assertFalse(self.owner_store.is_owner_banned(self.account_a.account_id))

    def test_http_admin_ban_requires_master_authorization(self) -> None:
        # Non-master caller attempts to ban Fleet A
        status, body = self._post(
            "/api/admin/fleet/ban",
            {"owner_id": self.account_a.account_id, "reason": "Hacker attempt"},
            headers={"X-Owner-Key": self.account_b.owner_key},
        )
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertFalse(self.fleet_store.is_fleet_banned(self.account_a.account_id))

    def test_http_admin_ban_and_unban_flow(self) -> None:
        master_headers = {"X-Master-Killswitch-Key": "master_secret_stripe_inetconnector_key"}

        # Master bans Fleet A
        status, body = self._post(
            "/api/admin/fleet/ban",
            {"owner_id": self.account_a.account_id, "reason": "Suspicious Activity"},
            headers=master_headers,
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body.get("action"), "ban")
        self.assertTrue(self.fleet_store.is_fleet_banned(self.account_a.account_id))

        # Master lists banned fleets
        status, body = self._get("/api/admin/fleet/banned", headers=master_headers)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(any(b["owner_id"] == self.account_a.account_id for b in body.get("banned_fleets", [])))

        # Fleet A queries /api/portal/fleet -> shows is_suspended
        status, fleet_payload = self._get(f"/api/portal/fleet?owner_key={self.account_a.owner_key}")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(fleet_payload.get("is_suspended"))
        self.assertEqual(fleet_payload.get("suspension_reason"), "Suspicious Activity")

        # Fleet B queries /api/portal/fleet -> is NOT suspended
        status, b_payload = self._get(f"/api/portal/fleet?owner_key={self.account_b.owner_key}")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertFalse(b_payload.get("is_suspended", False))

        # Master unbans Fleet A
        status, body = self._post(
            "/api/admin/fleet/unban",
            {"owner_id": self.account_a.account_id, "reason": "Audit complete"},
            headers=master_headers,
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body.get("action"), "unban")
        self.assertFalse(self.fleet_store.is_fleet_banned(self.account_a.account_id))

    def test_gateway_auth_manager_blocks_banned_fleet(self) -> None:
        ledger = Ledger(storage_path=Path(self.tmp_dir.name) / "ledger.json")
        teaser_mgr = TeaserQuotaManager()
        auth_mgr = GatewayAuthManager(ledger=ledger, teaser_manager=teaser_mgr, owner_account_store=self.owner_store)

        # Normal auth before ban
        headers = {"Authorization": f"Bearer {self.account_a.owner_key}"}
        res = auth_mgr.authenticate_request(headers)
        self.assertTrue(res.is_authenticated)

        # Ban Fleet A
        self.fleet_store.ban_fleet(self.account_a.account_id, reason="Malicious prompt injection")

        # Auth after ban
        res_banned = auth_mgr.authenticate_request(headers)
        self.assertFalse(res_banned.is_authenticated)
        self.assertEqual(res_banned.status_code, HTTPStatus.FORBIDDEN)
        self.assertIn("dauerhaft gesperrt", res_banned.error_message or "")

        # Fleet B is still completely authenticated
        res_b = auth_mgr.authenticate_request({"Authorization": f"Bearer {self.account_b.owner_key}"})
        self.assertTrue(res_b.is_authenticated)

    def test_inference_engine_blocks_banned_fleet(self) -> None:
        from services.gateway.metrics_exporter import MetricsRegistry
        ledger = Ledger(storage_path=Path(self.tmp_dir.name) / "ledger.json")
        ledger.deposit_customer_credits(customer_account_id=self.account_a.account_id, amount_micro_units=50_000_000, payment_reference="test")
        teaser_mgr = TeaserQuotaManager()
        metrics = MetricsRegistry()
        engine = InferenceEngine(ledger=ledger, metrics=metrics, teaser_manager=teaser_mgr)

        # Ban Fleet A
        self.fleet_store.ban_fleet(self.account_a.account_id, reason="Security threat")

        # Running inference for Fleet A raises EmergencyKillTrippedError
        with self.assertRaises(EmergencyKillTrippedError) as ctx:
            engine.create_metered_completion(
                account_id=self.account_a.account_id,
                model_id="qwen2.5:0.5b",
                messages=[{"role": "user", "content": "Hello"}],
                is_teaser=False,
            )
        self.assertIn("Fleet", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
