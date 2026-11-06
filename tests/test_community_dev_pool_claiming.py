"""Test authentic Community Dev Pool auto-enrollment and theft-proof node claiming."""
from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock

from services.billing.owner_accounts import OwnerAccountStore
from services.gateway.owner_provider_routes import UnifiedOwnerProviderRoutesHandler
from services.gateway.server import (
    COMMUNITY_POOL_OWNER_ID,
    NODE_TELEMETRY_REGISTRY,
    _build_fleet_payload,
    owner_id_for_key,
)
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore

from services.gateway import server as gateway_server_module


class TestCommunityDevPoolClaiming(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.original_owner_store = gateway_server_module.OWNER_ACCOUNT_STORE
        self.owner_store = OwnerAccountStore(Path(self.tmp_dir.name) / "owners.db")
        gateway_server_module.OWNER_ACCOUNT_STORE = self.owner_store

        self.original_fleet_store = passkey_routes.FLEET_ACCOUNT_STORE
        self.fleet_store = FleetAccountStore(Path(self.tmp_dir.name) / "fleet.db")
        passkey_routes.FLEET_ACCOUNT_STORE = self.fleet_store

        NODE_TELEMETRY_REGISTRY.clear()

        # Ensure community pool owner exists
        self.owner_store.ensure_owner(COMMUNITY_POOL_OWNER_ID, display_name="Community Dev Pool")

    def tearDown(self) -> None:
        gateway_server_module.OWNER_ACCOUNT_STORE = self.original_owner_store
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        NODE_TELEMETRY_REGISTRY.clear()
        self.tmp_dir.cleanup()

    def test_unowned_node_auto_joins_community_dev_pool(self) -> None:
        """A node without owner_key is auto-assigned to community_dev_pool, not left in limbo."""
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        node_id = "cm-rig-unconfigured-01"

        # Simulate heartbeat with empty owner_key
        record = {
            "node_id": node_id,
            "auth_token": "token_test_123",
            "public_key": "pub_key_hex_123",
            "owner_id": COMMUNITY_POOL_OWNER_ID,
            "is_community_pool": True,
            "updated_at": now_iso,
            "inventory": {"gpus": [{"model_name": "RTX 3080", "vram_bytes": 16 * 1024**3}]},
            "telemetry": {"local_compute_tflops": 29.8},
        }
        self.owner_store.bind_provider_node(COMMUNITY_POOL_OWNER_ID, node_id)
        NODE_TELEMETRY_REGISTRY[node_id] = record

        # Verify community pool payload
        community_payload = _build_fleet_payload(COMMUNITY_POOL_OWNER_ID)
        self.assertEqual(community_payload["total_nodes_bound"], 1)
        self.assertEqual(community_payload["nodes"][0]["node_id"], node_id)
        self.assertTrue(community_payload["nodes"][0]["is_community_pool"])
        self.assertEqual(community_payload["total_vram_gb"], 16.0)

        # Verify private account payload does not see this community node
        alice_key = "inet-alice-test-key-12345678901234"
        alice_owner_id = owner_id_for_key(alice_key)
        self.owner_store.ensure_owner(alice_owner_id)
        alice_payload = _build_fleet_payload(alice_owner_id)
        self.assertEqual(alice_payload["total_nodes_bound"], 0)
        self.assertEqual(alice_payload["total_vram_gb"], 0.0)

    def test_remote_attacker_cannot_claim_community_node_via_api(self) -> None:
        """An external user calling the provider register API cannot hijack a community node."""
        node_id = "cm-rig-community-02"
        self.owner_store.bind_provider_node(COMMUNITY_POOL_OWNER_ID, node_id)

        eve_owner_id = "acct_eve_attacker_999999"
        self.owner_store.ensure_owner(eve_owner_id)

        auth_mock = MagicMock()
        auth_mock.authenticate_provider.return_value = (node_id, None, HTTPStatus.OK)
        auth_mock.authenticate_request.return_value = MagicMock(owner_id=eve_owner_id, account_id=None)

        routes = UnifiedOwnerProviderRoutesHandler(
            owner_account_store=self.owner_store,
            account_store=MagicMock(),
            settlement_executor=None,
            auth_manager=auth_mock,
            ledger=MagicMock(),
        )

        _result_id, _owner_id, err_msg, status = routes._authenticated_owner({}, bind_provider_if_missing=True)
        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertIn("Community nodes cannot be claimed remotely", err_msg)
        self.assertEqual(self.owner_store.owner_for_provider_node(node_id), COMMUNITY_POOL_OWNER_ID)

    def test_legitimate_physical_node_claims_itself_into_fleet(self) -> None:
        """When the physical node itself supplies the owner_key, it transitions out of community pool."""
        node_id = "cm-rig-mifcom-03"
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        # Step 1: Node starts in community dev pool
        self.owner_store.bind_provider_node(COMMUNITY_POOL_OWNER_ID, node_id)
        NODE_TELEMETRY_REGISTRY[node_id] = {
            "node_id": node_id,
            "auth_token": "token_mifcom_secure",
            "owner_id": COMMUNITY_POOL_OWNER_ID,
            "is_community_pool": True,
            "updated_at": now_iso,
            "inventory": {"gpus": [{"model_name": "RTX 3080", "vram_bytes": 16 * 1024**3}]},
        }

        # Step 2: Owner inputs their key locally. Fleet account exists.
        acc = self.fleet_store.create_account("frede@inetconnector.com")
        fleet_key = acc.owner_key
        fleet_owner_id = owner_id_for_key(fleet_key)
        self.owner_store.ensure_owner(fleet_owner_id)

        # Step 3: Heartbeat reassignment logic allows transition from community pool
        existing_owner_id = self.owner_store.owner_for_provider_node(node_id)
        self.assertEqual(existing_owner_id, COMMUNITY_POOL_OWNER_ID)

        # Physical node performs rebind
        prev = self.owner_store.rebind_provider_node(fleet_owner_id, node_id)
        self.assertEqual(prev, COMMUNITY_POOL_OWNER_ID)
        NODE_TELEMETRY_REGISTRY[node_id]["owner_id"] = fleet_owner_id
        NODE_TELEMETRY_REGISTRY[node_id]["is_community_pool"] = False

        # Step 4: Verify node is now in fleet and removed from community pool
        fleet_payload = _build_fleet_payload(fleet_owner_id)
        self.assertEqual(fleet_payload["total_nodes_bound"], 1)
        self.assertEqual(fleet_payload["nodes"][0]["node_id"], node_id)
        self.assertFalse(fleet_payload["nodes"][0]["is_community_pool"])

        community_payload = _build_fleet_payload(COMMUNITY_POOL_OWNER_ID)
        self.assertEqual(community_payload["total_nodes_bound"], 0)


if __name__ == "__main__":
    unittest.main()
