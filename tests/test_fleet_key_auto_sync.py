"""Unit tests for automatic fleet owner key pulling and client synchronization."""
from http import HTTPStatus
import json
from pathlib import Path
import tempfile
import unittest

from services.billing.owner_accounts import OwnerAccountStore
from services.gateway import server as gateway_server_module
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore


class TestFleetKeyAutoSync(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.tmp_dir.name)
        self.fleet_db = self.work_dir / "fleet.db"
        self.owner_db = self.work_dir / "owner_accounts.db"

        self.fleet_store = FleetAccountStore(self.fleet_db)
        self.owner_store = OwnerAccountStore(self.owner_db)

        self.original_fleet_store = passkey_routes.FLEET_ACCOUNT_STORE
        self.original_gateway_fleet_store = gateway_server_module.FLEET_ACCOUNT_STORE
        self.original_gateway_owner_store = gateway_server_module.OWNER_ACCOUNT_STORE

        passkey_routes.FLEET_ACCOUNT_STORE = self.fleet_store
        gateway_server_module.FLEET_ACCOUNT_STORE = self.fleet_store
        gateway_server_module.OWNER_ACCOUNT_STORE = self.owner_store
        gateway_server_module.NODE_TELEMETRY_REGISTRY.clear()

    def tearDown(self) -> None:
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        gateway_server_module.FLEET_ACCOUNT_STORE = self.original_gateway_fleet_store
        gateway_server_module.OWNER_ACCOUNT_STORE = self.original_gateway_owner_store
        gateway_server_module.NODE_TELEMETRY_REGISTRY.clear()
        self.tmp_dir.cleanup()

    def test_key_rotation_transitive_resolution(self) -> None:
        acc = self.fleet_store.create_account("operator@inetconnector.com")
        initial_key = acc.owner_key
        self.assertTrue(initial_key.startswith("inet-"))

        # Rotate key once
        key2 = self.fleet_store.rotate_owner_key(acc.account_id)
        self.assertTrue(key2.startswith("inet-"))
        self.assertNotEqual(initial_key, key2)

        # Resolving initial_key returns key2
        self.assertEqual(self.fleet_store.resolve_latest_owner_key(initial_key), key2)
        self.assertEqual(self.fleet_store.resolve_latest_owner_key(key2), key2)

        # Rotate key a second time (chain)
        key3 = self.fleet_store.rotate_owner_key(acc.account_id)
        self.assertTrue(key3.startswith("inet-"))
        self.assertNotEqual(key2, key3)

        # Both initial_key and key2 resolve directly to key3
        self.assertEqual(self.fleet_store.resolve_latest_owner_key(initial_key), key3)
        self.assertEqual(self.fleet_store.resolve_latest_owner_key(key2), key3)
        self.assertEqual(self.fleet_store.resolve_latest_owner_key(key3), key3)

    def test_owner_account_bindings_migration(self) -> None:
        old_owner_id = "acct_old_owner_11111"
        new_owner_id = "acct_new_owner_22222"

        self.owner_store.ensure_owner(old_owner_id)
        self.owner_store.bind_provider_node(old_owner_id, "node_gpu_01")
        self.owner_store.bind_provider_node(old_owner_id, "node_gpu_02")
        self.owner_store.bind_device(old_owner_id, "device_mac_01")

        self.assertEqual(len(self.owner_store.list_provider_nodes(old_owner_id)), 2)

        # Migrate bindings
        moved = self.owner_store.migrate_owner_bindings(old_owner_id, new_owner_id)
        self.assertEqual(moved, 3)

        self.assertEqual(len(self.owner_store.list_provider_nodes(old_owner_id)), 0)
        self.assertEqual(len(self.owner_store.list_provider_nodes(new_owner_id)), 2)
        self.assertEqual(self.owner_store.owner_for_provider_node("node_gpu_01"), new_owner_id)
        self.assertEqual(self.owner_store.owner_for_provider_node("node_gpu_02"), new_owner_id)

    def test_passkey_route_rotate_key_migrates_nodes(self) -> None:
        handler = passkey_routes.PasskeyAuthHandler()
        acc = self.fleet_store.create_account("miner@inetconnector.com")
        initial_key = acc.owner_key
        initial_owner_id = gateway_server_module.owner_id_for_key(initial_key)

        self.owner_store.ensure_owner(initial_owner_id)
        self.owner_store.bind_provider_node(initial_owner_id, "rig_alpha")
        gateway_server_module.NODE_TELEMETRY_REGISTRY["rig_alpha"] = {
            "node_id": "rig_alpha",
            "owner_id": initial_owner_id,
        }

        # Create session
        token = self.fleet_store.create_session(acc.account_id)

        class FakeHeaders(dict):
            def get(self, key, default=""):
                return dict.get(self, key, default)

        headers = FakeHeaders({"Cookie": f"{passkey_routes.SESSION_COOKIE_NAME}={token}"})

        # Rotate key via handler
        data, status, _ = handler.rotate_owner_key(headers, {})
        self.assertEqual(status, HTTPStatus.OK)
        new_key = data["owner_key"]
        new_owner_id = gateway_server_module.owner_id_for_key(new_key)

        # Confirm rig_alpha was migrated in owner_store and in-memory registry
        self.assertEqual(self.owner_store.owner_for_provider_node("rig_alpha"), new_owner_id)
        self.assertEqual(gateway_server_module.NODE_TELEMETRY_REGISTRY["rig_alpha"]["owner_id"], new_owner_id)

    def test_heartbeat_auto_resolves_rotated_key(self) -> None:
        acc = self.fleet_store.create_account("auto@inetconnector.com")
        initial_key = acc.owner_key
        # Rotate key
        new_key = self.fleet_store.rotate_owner_key(acc.account_id)

        # Heartbeat sent with old initial_key
        resolved = self.fleet_store.resolve_latest_owner_key(initial_key)
        self.assertEqual(resolved, new_key)
        self.assertTrue(resolved.startswith("inet-"))


if __name__ == "__main__":
    unittest.main()
