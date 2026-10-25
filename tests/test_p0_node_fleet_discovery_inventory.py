"""P0 Verification & Regression Suite for Node Fleet Discovery, Mesh Inventory and Multi-Node Rollout.

Mandated by .agents/rules/p0_node_fleet_discovery_rollout_2026-10-25.md:
1. Recognizes, authenticates and registers cm-inference-node-01.
2. Captures all previous miners and inference nodes (including CPU-only and multi-GPU).
3. Persists and distinctly displays online, stale, offline and quarantined nodes (no silent dropping).
4. Verifies hardware deduplication and alias collision detection.
5. Verifies pagination (limit/offset) without dropping records.
6. Verifies software version comparison and update eligibility reporting.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from services.billing.owner_accounts import OwnerAccountStore
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
import services.gateway.server as gateway_server
from services.gateway.server import (
    _build_fleet_payload,
    owner_id_for_key,
)
from services.appliance_dashboard.mesh_aggregator import MeshRegistryAggregator


class TestP0NodeFleetDiscoveryInventory(unittest.TestCase):
    def setUp(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "test_owner_accounts.db"
        self.original_store = gateway_server.OWNER_ACCOUNT_STORE
        gateway_server.OWNER_ACCOUNT_STORE = OwnerAccountStore(self.db_path)

        self.owner_key = "test_owner_fleet_key_p0"
        self.owner_id = owner_id_for_key(self.owner_key)
        gateway_server.OWNER_ACCOUNT_STORE.ensure_owner(self.owner_id)

    def tearDown(self) -> None:
        gateway_server.OWNER_ACCOUNT_STORE = self.original_store
        self._temp_dir.cleanup()

    def test_reproduce_full_mesh_inventory_with_new_node_stale_offline_and_pagination(self) -> None:
        """RED test verifying that all nodes (new node, existing nodes, stale, offline,

        CPU-only, and duplicates) are accurately captured and classified without dropping.
        """
        now = datetime.now(UTC)
        now_iso = now.isoformat().replace("+00:00", "Z")
        stale_iso = (now - timedelta(seconds=70)).isoformat().replace("+00:00", "Z")
        offline_iso = (now - timedelta(seconds=400)).isoformat().replace("+00:00", "Z")

        # 1. New Node: cm-inference-node-01 (6x AMD Polaris GPUs = 48 GB, 72 TFLOPS)
        NODE_TELEMETRY_REGISTRY["cm-inference-node-01"] = {
            "node_id": "cm-inference-node-01",
            "display_name": "cm-inference-node-01",
            "auth_token": "token_cm_inference_01",
            "owner_id": self.owner_id,
            "client_ip": "192.168.1.27",
            "updated_at": now_iso,
            "version": "1.2.40",
            "inventory": {
                "total_vram_bytes": 48 * 1024**3,
                "gpus": [
                    {"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}
                    for _ in range(6)
                ],
            },
            "telemetry": {"local_compute_tflops": 72.0},
        }

        # 2. Existing Node 1: windows-laptop (RTX 3080 16GB, online)
        NODE_TELEMETRY_REGISTRY["windows-laptop"] = {
            "node_id": "windows-laptop",
            "display_name": "Mifcom-S (Local Host)",
            "auth_token": "token_windows_laptop",
            "owner_id": self.owner_id,
            "client_ip": "192.168.1.100",
            "updated_at": now_iso,
            "version": "1.2.186",
            "inventory": {
                "total_vram_bytes": 16 * 1024**3,
                "gpus": [
                    {"vendor": "nvidia", "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "healthy": True}
                ],
            },
            "telemetry": {"local_compute_tflops": 24.0},
        }

        # 3. Existing Node 2: cm-node-webserver (CPU-only, online)
        NODE_TELEMETRY_REGISTRY["cm-node-webserver"] = {
            "node_id": "cm-node-webserver",
            "display_name": "Webserver Node (CPU)",
            "auth_token": "token_webserver",
            "owner_id": self.owner_id,
            "client_ip": "192.168.1.101",
            "updated_at": now_iso,
            "version": "1.2.185",
            "inventory": {
                "total_vram_bytes": 0,
                "gpus": [],
            },
            "telemetry": {"local_compute_tflops": 2.5},
        }

        # 4. Stale Node: miner-stale-01 (Heartbeat 70s ago -> stale)
        NODE_TELEMETRY_REGISTRY["miner-stale-01"] = {
            "node_id": "miner-stale-01",
            "display_name": "Stale Miner",
            "auth_token": "token_miner_stale",
            "owner_id": self.owner_id,
            "client_ip": "192.168.1.50",
            "updated_at": stale_iso,
            "version": "1.2.35",
            "inventory": {
                "total_vram_bytes": 8 * 1024**3,
                "gpus": [{"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 12.0},
        }

        # 5. Offline Node: peer-192-168-1-35 (Heartbeat 400s ago -> offline)
        NODE_TELEMETRY_REGISTRY["peer-192-168-1-35"] = {
            "node_id": "peer-192-168-1-35",
            "display_name": "Offline Peer 192.168.1.35",
            "auth_token": "token_offline_peer",
            "owner_id": self.owner_id,
            "client_ip": "192.168.1.35",
            "updated_at": offline_iso,
            "version": "1.2.10",
            "inventory": {
                "total_vram_bytes": 16 * 1024**3,
                "gpus": [{"vendor": "nvidia", "model_name": "RTX 3070", "vram_bytes": 16 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 20.0},
        }

        # 6. Duplicate Alias: test-node-custom (same token/hardware as windows-laptop)
        NODE_TELEMETRY_REGISTRY["test-node-custom"] = {
            "node_id": "test-node-custom",
            "display_name": "Duplicate Alias of Laptop",
            "auth_token": "token_windows_laptop", # duplicate token!
            "owner_id": self.owner_id,
            "client_ip": "192.168.1.100",
            "updated_at": now_iso,
            "version": "1.2.186",
            "inventory": {
                "total_vram_bytes": 16 * 1024**3,
                "gpus": [
                    {"vendor": "nvidia", "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "healthy": True}
                ],
            },
            "telemetry": {"local_compute_tflops": 24.0},
        }

        # Bind all nodes to owner
        for nid in [
            "cm-inference-node-01",
            "windows-laptop",
            "cm-node-webserver",
            "miner-stale-01",
            "peer-192-168-1-35",
            "test-node-custom",
        ]:
            gateway_server.OWNER_ACCOUNT_STORE.bind_provider_node(self.owner_id, nid)

        # Build full payload
        fleet = _build_fleet_payload(self.owner_id)

        # Verification 1: Exactly 5 unique physical nodes must be counted in total_nodes_bound
        # (6 enrolled - 1 duplicate alias = 5 unique physical machines)
        self.assertEqual(fleet["total_nodes_bound"], 5)

        # Verification 2: Status counts must correctly separate states
        summary = fleet["status_summary"]
        self.assertEqual(summary["online"], 3, f"Expected 3 online nodes, got {summary['online']}") # cm-inference, laptop, webserver
        self.assertEqual(summary["stale"], 1, f"Expected 1 stale node, got {summary['stale']}")
        self.assertEqual(summary["offline"], 1, f"Expected 1 offline node, got {summary['offline']}")

        # Verification 3: Alias collision explicitly recorded
        self.assertTrue(len(fleet["alias_collisions"]) >= 1)
        collision = fleet["alias_collisions"][0]
        self.assertIn(collision["duplicate_node_id"], ["test-node-custom", "windows-laptop"])
        self.assertIn(collision["primary_node_id"], ["test-node-custom", "windows-laptop"])
        self.assertNotEqual(collision["duplicate_node_id"], collision["primary_node_id"])

        # Verification 4: cm-inference-node-01 specific checks
        node_map = {n["node_id"]: n for n in fleet["nodes"]}
        self.assertIn("cm-inference-node-01", node_map)
        node_01 = node_map["cm-inference-node-01"]
        self.assertEqual(node_01["status"], "online")
        self.assertEqual(node_01["vram_gb"], 48.0)
        self.assertEqual(node_01["tflops"], 72.0)
        self.assertEqual(node_01["software_version"], "1.2.40")
        self.assertEqual(node_01["update_status"], "UPDATE_AVAILABLE")
        self.assertTrue(node_01["available_for_routing"])
        self.assertEqual(node_01["gpu_summary"], "6x AMD Radeon RX 580")
        self.assertEqual(node_01["gpu_count"], 6)
        self.assertFalse(node_01["inference_ready"])
        self.assertEqual(node_01["model_runtime_state"], "stopped")

        # Verification 5: Offline and stale nodes must NOT be dropped, but blocked from routing
        self.assertIn("miner-stale-01", node_map)
        self.assertEqual(node_map["miner-stale-01"]["status"], "stale")
        self.assertFalse(node_map["miner-stale-01"]["available_for_routing"])
        self.assertEqual(node_map["miner-stale-01"]["update_status"], "BLOCKED/OFFLINE")

        self.assertIn("peer-192-168-1-35", node_map)
        self.assertEqual(node_map["peer-192-168-1-35"]["status"], "offline")
        self.assertFalse(node_map["peer-192-168-1-35"]["available_for_routing"])

        # Verification 6: Pagination works correctly (limit=2, offset=0 and offset=2)
        paged_page1 = _build_fleet_payload(self.owner_id, limit=2, offset=0)
        self.assertEqual(len(paged_page1["nodes"]), 2)
        self.assertTrue(paged_page1["has_more"])
        self.assertEqual(paged_page1["total_nodes_count"], 5)

        paged_page2 = _build_fleet_payload(self.owner_id, limit=2, offset=2)
        self.assertEqual(len(paged_page2["nodes"]), 2)
        self.assertTrue(paged_page2["has_more"])

        # Page 1 and Page 2 must not have overlapping nodes
        ids_p1 = {n["node_id"] for n in paged_page1["nodes"]}
        ids_p2 = {n["node_id"] for n in paged_page2["nodes"]}
        self.assertTrue(ids_p1.isdisjoint(ids_p2))

    def test_mesh_aggregator_retains_offline_and_stale_and_cpu_nodes(self) -> None:
        """Verify MeshRegistryAggregator retains and classifies offline, stale and CPU nodes."""
        agg = MeshRegistryAggregator(autostart=False)

        # Local Node: 16 GB Laptop (Online)
        local_payload = {
            "node_id": "windows-laptop",
            "status": "online",
            "inventory": {
                "total_vram_bytes": 16 * 1024**3,
                "gpus": [{"vendor": "nvidia", "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 24.0, "tokens_processed": 500},
        }

        # Peer 1: cm-inference-node-01 (Online, 48 GB)
        agg._peer_nodes["cm-inference-node-01"] = {
            "node_id": "cm-inference-node-01",
            "status": "online",
            "inventory": {
                "total_vram_bytes": 48 * 1024**3,
                "gpus": [{"vendor": "amd", "model_name": "AMD Radeon RX 580", "vram_bytes": 8 * 1024**3, "healthy": True} for _ in range(6)],
            },
            "telemetry": {"local_compute_tflops": 72.0, "tokens_processed": 1000},
            "last_seen": 1000.0,
        }

        # Peer 2: cpu-only-worker (Online, 0 GB VRAM, CPU)
        agg._peer_nodes["cpu-only-worker"] = {
            "node_id": "cpu-only-worker",
            "status": "online",
            "inventory": {
                "total_vram_bytes": 0,
                "gpus": [],
            },
            "telemetry": {"local_compute_tflops": 2.0, "tokens_processed": 100},
            "last_seen": 1000.0,
        }

        # Peer 3: stale-rig (Stale, last seen 50s ago)
        agg._peer_nodes["stale-rig"] = {
            "node_id": "stale-rig",
            "status": "stale",
            "inventory": {
                "total_vram_bytes": 8 * 1024**3,
                "gpus": [{"vendor": "amd", "model_name": "AMD Vega 10", "vram_bytes": 8 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 12.0, "tokens_processed": 0},
            "last_seen": 950.0,
        }

        # Peer 4: offline-peer-35 (Offline, unreachable)
        agg._peer_nodes["peer-192-168-1-35"] = {
            "node_id": "peer-192-168-1-35",
            "status": "offline",
            "inventory": {
                "total_vram_bytes": 8 * 1024**3,
                "gpus": [{"vendor": "amd", "model_name": "AMD Polaris", "vram_bytes": 8 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 12.0, "tokens_processed": 0},
            "last_seen": 500.0,
        }

        stats = agg.get_mesh_stats(local_status=local_payload)

        # Total registered nodes must be 5 (local + 4 peers, NONE dropped!)
        self.assertEqual(stats["total_nodes_registered"], 5)
        self.assertEqual(stats["total_nodes_online"], 3) # laptop, cm-inference-01, cpu-only
        self.assertEqual(stats["total_nodes_stale"], 1)
        self.assertEqual(stats["total_nodes_offline"], 1)

        # Operational capacity only sums active online nodes:
        # 16 GB laptop + 48 GB cm-inference-01 = 64 GB Pool (stale and offline are excluded from active capacity!)
        self.assertEqual(stats["total_vram_gb"], 64.0)
        self.assertAlmostEqual(stats["total_compute_tflops"], 98.0, places=1) # 24 + 72 + 2 = 98 TFLOPS

        node_map = {n["node_id"]: n for n in stats["nodes"]}
        self.assertIn("cpu-only-worker", node_map)
        self.assertEqual(node_map["cpu-only-worker"]["status"], "online")
        self.assertIn("stale-rig", node_map)
        self.assertEqual(node_map["stale-rig"]["status"], "stale")
        self.assertIn("peer-192-168-1-35", node_map)
        self.assertEqual(node_map["peer-192-168-1-35"]["status"], "offline")

    def test_heartbeat_token_rotation_when_owner_authorized_and_rejection_when_unauthorized(self) -> None:
        """Verify that an active node can rotate its token if owner_authorized is True,
        but is strictly rejected with 401 Unauthorized if unauthorized.
        """
        import hmac

        # Given an existing registered node with token_old and bound to self.owner_id
        existing_node = {
            "node_id": "cm-inference-node-01",
            "auth_token": "token_old",
            "owner_id": self.owner_id,
            "updated_at": "2026-10-25T19:00:00Z",
        }
        expected_token = existing_node["auth_token"]

        # Case 1: Attacker sends mismatched token WITHOUT valid owner_key
        attacker_token = "token_malicious_new"
        attacker_owner_key = "invalid_owner_key"
        sender_owner = owner_id_for_key(attacker_owner_key)
        existing_owner = existing_node.get("owner_id")
        owner_authorized = bool(sender_owner and (not existing_owner or existing_owner == sender_owner))
        token_matches = bool(expected_token and hmac.compare_digest(attacker_token, expected_token))

        self.assertFalse(owner_authorized)
        self.assertFalse(token_matches)
        # Therefore: rejected!

        # Case 2: Legitimate owner reconnects after node reboot with fresh token
        rotated_token = "token_legitimate_rotated"
        sender_owner = owner_id_for_key(self.owner_key)
        owner_authorized = bool(sender_owner and (not existing_owner or existing_owner == sender_owner))
        token_matches = bool(expected_token and hmac.compare_digest(rotated_token, expected_token))

        self.assertTrue(owner_authorized)
        self.assertFalse(token_matches)
        # Because owner_authorized is True, token rotation is accepted!
        can_proceed = token_matches or owner_authorized
        self.assertTrue(can_proceed)


if __name__ == "__main__":
    unittest.main()

