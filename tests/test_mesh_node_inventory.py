"""Comprehensive P0 test suite for mesh node inventory, stale/offline retention, alias collision detection,
controlled updates, and pagination (2026-10-25)."""
from datetime import datetime, timezone, timedelta
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import tempfile
import threading
import time
import unittest
import urllib.request

from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
import services.gateway.server as gateway_server_module
from services.billing.owner_accounts import OwnerAccountStore
from services.portal.server import PortalHandler
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore
from config import CONFIG

PORT = 13028
BASE = f"http://127.0.0.1:{PORT}"


class TestMeshNodeInventoryP0(unittest.TestCase):
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
        self.original_owner_store = gateway_server_module.OWNER_ACCOUNT_STORE
        self.owner_store = OwnerAccountStore(Path(self.tmp_dir.name) / "owners.db")
        gateway_server_module.OWNER_ACCOUNT_STORE = self.owner_store

        self.original_fleet_store = passkey_routes.FLEET_ACCOUNT_STORE
        self.fleet_store = FleetAccountStore(Path(self.tmp_dir.name) / "fleet.db")
        passkey_routes.FLEET_ACCOUNT_STORE = self.fleet_store

        NODE_TELEMETRY_REGISTRY.clear()

    def tearDown(self) -> None:
        gateway_server_module.OWNER_ACCOUNT_STORE = self.original_owner_store
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        NODE_TELEMETRY_REGISTRY.clear()
        self.tmp_dir.cleanup()

    def test_reproduce_and_verify_node_inventory_lifecycle(self) -> None:
        now = datetime.now(timezone.utc)
        owner_id = "owner_test_p0"
        self.owner_store.ensure_owner(owner_id)

        # 1. New inference node reported by operator: cm-inference-node-01 (fresh heartbeat)
        NODE_TELEMETRY_REGISTRY["cm-inference-node-01"] = {
            "node_id": "cm-inference-node-01",
            "name": "CM Inference Node 01",
            "auth_token": "token_cm_01",
            "client_ip": "192.168.1.101",
            "version": CONFIG.appliance_version,
            "commit_sha": "0536423",
            "protocol_version": 2,
            "models": ["llama-3.2-3b-instruct", "mistral-7b-instruct"],
            "inventory": {
                "gpus": [{"model_name": "NVIDIA GeForce RTX 4090", "vram_bytes": 24 * 1024**3, "vendor": "nvidia"}],
                "total_vram_bytes": 24 * 1024**3
            },
            "telemetry": {"local_compute_tflops": 82.5},
            "updated_at": (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "cm-inference-node-01")

        # 2. Existing live node: node-existing-primary (fresh heartbeat)
        NODE_TELEMETRY_REGISTRY["node-existing-primary"] = {
            "node_id": "node-existing-primary",
            "name": "Primary Cluster Rig",
            "auth_token": "token_existing_pri",
            "client_ip": "192.168.1.102",
            "version": CONFIG.appliance_version,
            "commit_sha": "0536423",
            "protocol_version": 2,
            "models": ["llama-3.2-3b-instruct"],
            "inventory": {
                "gpus": [{"model_name": "NVIDIA RTX A6000", "vram_bytes": 48 * 1024**3, "vendor": "nvidia"}],
                "total_vram_bytes": 48 * 1024**3
            },
            "telemetry": {"local_compute_tflops": 75.0},
            "updated_at": (now - timedelta(seconds=15)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "node-existing-primary")

        # 3. Existing stale node: node-existing-stale (heartbeat 90s ago -> stale, between 45s and 300s)
        NODE_TELEMETRY_REGISTRY["node-existing-stale"] = {
            "node_id": "node-existing-stale",
            "name": "Stale Secondary Worker",
            "auth_token": "token_existing_stale",
            "client_ip": "192.168.1.103",
            "version": "1.2.184",
            "commit_sha": "cbe1a14",
            "protocol_version": 2,
            "inventory": {
                "gpus": [{"model_name": "NVIDIA GeForce RTX 3090", "vram_bytes": 24 * 1024**3, "vendor": "nvidia"}],
                "total_vram_bytes": 24 * 1024**3
            },
            "telemetry": {"local_compute_tflops": 35.5},
            "updated_at": (now - timedelta(seconds=90)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "node-existing-stale")

        # 4. Offline node: node-offline-historic (heartbeat 1 hour ago -> offline, must NEVER be popped from registry)
        NODE_TELEMETRY_REGISTRY["node-offline-historic"] = {
            "node_id": "node-offline-historic",
            "name": "Historic Offline Rig",
            "auth_token": "token_offline_historic",
            "client_ip": "192.168.1.104",
            "version": "1.2.180",
            "commit_sha": "b78d6fd",
            "protocol_version": 1,
            "inventory": {
                "gpus": [{"model_name": "NVIDIA GeForce RTX 3080", "vram_bytes": 10 * 1024**3, "vendor": "nvidia"}],
                "total_vram_bytes": 10 * 1024**3
            },
            "telemetry": {"local_compute_tflops": 29.0},
            "updated_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "node-offline-historic")

        # 5. Quarantined node: node-quarantined-rogue (untrusted or quarantined)
        NODE_TELEMETRY_REGISTRY["node-quarantined-rogue"] = {
            "node_id": "node-quarantined-rogue",
            "name": "Rogue Node",
            "auth_token": "token_rogue",
            "client_ip": "192.168.1.105",
            "is_quarantined": True,
            "quarantine_reason": "Failed cryptographic challenge attestation",
            "updated_at": (now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "node-quarantined-rogue")

        # 6. Alias / duplicate node: node-alias-dup (reuses token_cm_01 from cm-inference-node-01)
        NODE_TELEMETRY_REGISTRY["node-alias-dup"] = {
            "node_id": "node-alias-dup",
            "name": "Alias Dup of CM01",
            "auth_token": "token_cm_01",
            "client_ip": "192.168.1.106",
            "updated_at": (now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "node-alias-dup")

        # Execute _build_fleet_payload for this owner
        payload = gateway_server_module._build_fleet_payload(owner_id)

        # Assertion A: Registry preservation - offline node must NOT be purged from NODE_TELEMETRY_REGISTRY
        self.assertIn("node-offline-historic", NODE_TELEMETRY_REGISTRY, "Offline node must not be purged from registry.")

        # Assertion B: Distinct statuses (online, stale, offline, quarantined)
        node_map = {n["node_id"]: n for n in payload["nodes"]}
        self.assertIn("cm-inference-node-01", node_map)
        self.assertIn("node-existing-primary", node_map)
        self.assertIn("node-existing-stale", node_map)
        self.assertIn("node-offline-historic", node_map)
        self.assertIn("node-quarantined-rogue", node_map)

        self.assertEqual(node_map["cm-inference-node-01"]["status"], "online")
        self.assertEqual(node_map["node-existing-primary"]["status"], "online")
        self.assertEqual(node_map["node-existing-stale"]["status"], "stale")
        self.assertEqual(node_map["node-offline-historic"]["status"], "offline")
        self.assertEqual(node_map["node-quarantined-rogue"]["status"], "quarantined")

        # Assertion C: Alias collision explicitly reported
        self.assertIn("alias_collisions", payload, "Payload must include alias_collisions list.")
        self.assertTrue(len(payload["alias_collisions"]) > 0, "Duplicate token must produce an alias collision.")
        self.assertEqual(payload["alias_collisions"][0]["duplicate_node_id"], "node-alias-dup")
        self.assertEqual(payload["alias_collisions"][0]["primary_node_id"], "cm-inference-node-01")

        # Assertion D: cm-inference-node-01 verification fields
        cm01 = node_map["cm-inference-node-01"]
        self.assertEqual(cm01["display_name"], "CM Inference Node 01")
        self.assertEqual(cm01["software_version"], CONFIG.appliance_version)
        self.assertEqual(cm01["commit_sha"], "0536423")
        self.assertEqual(cm01["capabilities"]["models"], ["llama-3.2-3b-instruct", "mistral-7b-instruct"])
        self.assertEqual(cm01["update_status"], "UP_TO_DATE")

        # Offline node update status must be BLOCKED/OFFLINE (never success)
        off_node = node_map["node-offline-historic"]
        self.assertEqual(off_node["update_status"], "BLOCKED/OFFLINE")

        # Assertion E: Pagination
        paged_payload = gateway_server_module._build_fleet_payload(owner_id, limit=2, offset=0)
        self.assertEqual(len(paged_payload["nodes"]), 2)
        self.assertTrue(paged_payload["has_more"])
        self.assertEqual(paged_payload["limit"], 2)
        self.assertEqual(paged_payload["offset"], 0)
        self.assertEqual(paged_payload["total_nodes_count"], len(payload["nodes"]))

    def test_http_api_portal_fleet_with_pagination_and_status(self) -> None:
        now = datetime.now(timezone.utc)
        owner_key = "cm_owner_inventory_http_test_key"
        owner_id = gateway_server_module.owner_id_for_key(owner_key)
        self.owner_store.ensure_owner(owner_id)

        # Register cm-inference-node-01 and an offline node
        NODE_TELEMETRY_REGISTRY["cm-inference-node-01"] = {
            "node_id": "cm-inference-node-01",
            "name": "CM Inference Node 01",
            "auth_token": "token_http_01",
            "version": CONFIG.appliance_version,
            "commit_sha": "0536423",
            "updated_at": (now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "cm-inference-node-01")

        NODE_TELEMETRY_REGISTRY["node-stale-02"] = {
            "node_id": "node-stale-02",
            "name": "Stale Node 02",
            "auth_token": "token_http_02",
            "version": "1.2.180",
            "updated_at": (now - timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
        }
        self.owner_store.bind_provider_node(owner_id, "node-stale-02")

        # Query HTTP API with limit=1, offset=0
        req = urllib.request.Request(
            f"{BASE}/api/portal/fleet?limit=1&offset=0",
            headers={"X-Owner-Key": owner_key}
        )
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(len(data["nodes"]), 1)
        self.assertEqual(data["total_nodes_count"], 2)
        self.assertTrue(data["has_more"])
        self.assertEqual(data["nodes"][0]["node_id"], "cm-inference-node-01")
        self.assertEqual(data["nodes"][0]["status"], "online")

        # Query HTTP API offset=1
        req2 = urllib.request.Request(
            f"{BASE}/api/portal/fleet?limit=1&offset=1",
            headers={"X-Owner-Key": owner_key}
        )
        resp2 = urllib.request.urlopen(req2)
        self.assertEqual(resp2.status, HTTPStatus.OK)
        data2 = json.loads(resp2.read().decode("utf-8"))

        self.assertEqual(len(data2["nodes"]), 1)
        self.assertEqual(data2["nodes"][0]["node_id"], "node-stale-02")
        self.assertEqual(data2["nodes"][0]["status"], "stale")
        self.assertFalse(data2["has_more"])


if __name__ == "__main__":
    unittest.main()
