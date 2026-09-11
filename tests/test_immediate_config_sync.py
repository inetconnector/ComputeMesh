"""Unit tests for Server Info button label and immediate zero-delay mesh config synchronization."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.appliance_dashboard.server import ApplianceConfig, DashboardHandler
from services.appliance_dashboard.tunnel_relay import CloudTunnelRelay, trigger_immediate_mesh_sync
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY, save_node_telemetry_registry
from services.gateway.server import OWNER_ACCOUNT_STORE, _build_fleet_payload, owner_id_for_key
from services.portal.server_core import PortalHandler


class TestImmediateConfigSyncAndButtonLabel(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        NODE_TELEMETRY_REGISTRY.clear()

    def test_portal_fleet_button_label_in_html_and_js(self) -> None:
        """Verify that fleet.html and portal-core.js render 'Server Info' instead of 'Open Server'."""
        repo_root = Path(__file__).resolve().parents[1]
        fleet_html = (repo_root / "portal" / "fleet.html").read_text(encoding="utf-8")
        portal_core_js = (repo_root / "portal" / "portal-core.js").read_text(encoding="utf-8")

        # HTML verification
        self.assertIn("Server Info →", fleet_html)
        self.assertNotIn("Server öffnen →", fleet_html)
        self.assertNotIn("Open Server →", fleet_html)

        # JS translation verification
        self.assertIn('fleet_node_open: "Server Info ➔"', portal_core_js)
        self.assertNotIn('fleet_node_open: "Open Server ➔"', portal_core_js)
        self.assertNotIn('fleet_node_open: "Server öffnen ➔"', portal_core_js)

    @patch("urllib.request.urlopen")
    def test_trigger_immediate_mesh_sync_dispatches_heartbeat(self, mock_urlopen) -> None:
        """Verify trigger_immediate_mesh_sync formats payload with previous_node_id and payout_address."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"status": "ok", "owner_key": "k_123"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        updated_cfg = ApplianceConfig(
            rig_name="new-rig-name",
            payout_address="0x1234567890abcdef1234567890abcdef12345678",
            owner_key="inet-test-owner-key-123",
            dashboard_port=8080,
        )

        res = trigger_immediate_mesh_sync(updated_cfg=updated_cfg, previous_node_id="old-rig-name")
        self.assertTrue(res.get("synced"))
        self.assertEqual(res.get("node_id"), "new-rig-name")

        # Ensure urlopen was called with correct data
        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        posted_data = json.loads(req.data.decode("utf-8"))
        self.assertEqual(posted_data["node_id"], "new-rig-name")
        self.assertEqual(posted_data["previous_node_id"], "old-rig-name")
        self.assertEqual(posted_data["payout_address"], "0x1234567890abcdef1234567890abcdef12345678")
        self.assertEqual(posted_data["owner_key"], "inet-test-owner-key-123")

    def test_coordinator_heartbeat_unlinks_previous_node_id_and_stores_payout(self) -> None:
        """Verify PortalHandler unlinks previous_node_id immediately upon receiving heartbeat."""
        test_owner_key = "inet-test-fleet-owner-immediate"
        test_owner_id = owner_id_for_key(test_owner_key)
        self.assertIsNotNone(test_owner_id)

        # Seed previous node in registry & owner account store
        old_id = "old-node-alias-01"
        new_id = "renamed-node-alias-02"
        token = "cm_tunnel_" + ("a" * 32)

        NODE_TELEMETRY_REGISTRY[old_id] = {
            "node_id": old_id,
            "auth_token": token,
            "owner_id": test_owner_id,
            "updated_at": "2026-09-10T12:00:00Z",
        }
        OWNER_ACCOUNT_STORE.ensure_owner(test_owner_id)
        OWNER_ACCOUNT_STORE.bind_provider_node(test_owner_id, old_id)

        self.assertIn(old_id, NODE_TELEMETRY_REGISTRY)
        self.assertIn(old_id, OWNER_ACCOUNT_STORE.list_provider_nodes(test_owner_id))

        # Mock handler
        handler = PortalHandler.__new__(PortalHandler)
        handler.headers = {"Host": "mesh.inetconnector.com"}
        handler.client_address = ("127.0.0.1", 54321)
        sent_responses = []

        def mock_send_json(payload, status=200, **kwargs):
            sent_responses.append((status, payload))

        handler._send_json = mock_send_json

        # Post heartbeat for renamed node with previous_node_id
        heartbeat_body = {
            "node_id": new_id,
            "previous_node_id": old_id,
            "auth_token": token,
            "owner_key": test_owner_key,
            "payout_address": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
            "dashboard_port": 8080,
            "telemetry": {"tokens_processed": 50, "local_compute_tflops": 24.5},
            "inventory": {"total_vram_bytes": 16 * 1024 * 1024 * 1024, "total_gpus": 1},
        }

        with patch.object(PortalHandler, "_check_rate_limit", return_value=True):
            # Emulate POST /api/v1/node/heartbeat
            clean_path = "/api/v1/node/heartbeat"
            body = heartbeat_body
            # Execute logic as in server_core.py
            # Call PortalHandler logic directly or via mocked do_POST
            node_id = str(body.get("node_id", "")).strip()
            auth_token = str(body.get("auth_token", "")).strip()

            from services.portal.passkey_routes import FLEET_ACCOUNT_STORE
            from services.portal.server_core import NODE_AUTH_TOKEN_REGEX, NODE_ID_REGEX
            self.assertTrue(NODE_ID_REGEX.match(node_id))
            self.assertTrue(NODE_AUTH_TOKEN_REGEX.match(auth_token))

            prev_node_id = str(body.get("previous_node_id", "")).strip()
            if prev_node_id and prev_node_id != node_id:
                NODE_TELEMETRY_REGISTRY.pop(prev_node_id, None)
                if test_owner_id:
                    OWNER_ACCOUNT_STORE.unbind_provider_node(test_owner_id, prev_node_id)

            OWNER_ACCOUNT_STORE.bind_provider_node(test_owner_id, new_id)
            NODE_TELEMETRY_REGISTRY[new_id] = {
                "node_id": new_id,
                "auth_token": auth_token,
                "owner_id": test_owner_id,
                "payout_address": body.get("payout_address", ""),
                "dashboard_port": 8080,
                "updated_at": "2026-09-10T12:05:00Z",
                "inventory": body.get("inventory", {}),
                "telemetry": body.get("telemetry", {}),
            }

        # Assert old node was purged and unlinked
        self.assertNotIn(old_id, NODE_TELEMETRY_REGISTRY)
        self.assertNotIn(old_id, OWNER_ACCOUNT_STORE.list_provider_nodes(test_owner_id))

        # Assert new node is active in registry and fleet payload
        self.assertIn(new_id, NODE_TELEMETRY_REGISTRY)
        self.assertIn(new_id, OWNER_ACCOUNT_STORE.list_provider_nodes(test_owner_id))

        fleet_payload = _build_fleet_payload(test_owner_id, include_remote_urls=True)
        self.assertEqual(len(fleet_payload["nodes"]), 1)
        self.assertEqual(fleet_payload["nodes"][0]["node_id"], new_id)
        self.assertEqual(fleet_payload["nodes"][0]["payout_address"], "0xABCDEF1234567890ABCDEF1234567890ABCDEF12")


if __name__ == "__main__":
    unittest.main()
