"""Unit tests for Hardware Fingerprint Deduplication and Single-Unit Node Enforcement."""
from __future__ import annotations

import unittest
from services.appliance_dashboard.mesh_aggregator import MeshRegistryAggregator
from services.gateway.dashboard import NODE_TELEMETRY_REGISTRY
from services.gateway.server import OWNER_ACCOUNT_STORE, _build_fleet_payload, owner_id_for_key


class TestHardwareDeduplication(unittest.TestCase):
    def setUp(self) -> None:
        NODE_TELEMETRY_REGISTRY.clear()

    def test_mesh_aggregator_collapses_same_gpu_aliases_to_one_unit(self) -> None:
        """Verify MeshRegistryAggregator never sums duplicate RTX 3080 Laptop 16GB entries."""
        agg = MeshRegistryAggregator(autostart=False)

        # 1. Local machine: cm-node-48GB-Miner with RTX 3080 Laptop (16 GB)
        local_payload = {
            "node_id": "cm-node-48GB-Miner",
            "status": "online",
            "inventory": {
                "total_vram_bytes": 16 * 1024 * 1024 * 1024,
                "gpus": [
                    {
                        "vendor": "NVIDIA",
                        "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU",
                        "vram_bytes": 16 * 1024 * 1024 * 1024,
                        "healthy": True,
                    }
                ],
            },
            "telemetry": {"local_compute_tflops": 24.0, "tokens_processed": 1000},
        }

        # 2. Peer node: Distinct hardware: AMD MI25 (8 GB)
        agg._peer_nodes["cm-inference-node-01"] = {
            "node_id": "cm-inference-node-01",
            "status": "online",
            "inventory": {
                "total_vram_bytes": 8 * 1024 * 1024 * 1024,
                "gpus": [
                    {
                        "vendor": "AMD",
                        "model_name": "AMD Radeon Instinct MI25",
                        "vram_bytes": 8 * 1024 * 1024 * 1024,
                        "healthy": True,
                    }
                ],
            },
            "telemetry": {"local_compute_tflops": 24.6, "tokens_processed": 500},
        }

        # 3. Duplicate aliases of the local laptop in peer cache (e.g. from previous names or self-polling)
        agg._peer_nodes["test-node-custom"] = {
            "node_id": "test-node-custom",
            "status": "online",
            "inventory": {
                "total_vram_bytes": 16 * 1024 * 1024 * 1024,
                "gpus": [
                    {
                        "vendor": "NVIDIA",
                        "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU",
                        "vram_bytes": 16 * 1024 * 1024 * 1024,
                        "healthy": True,
                    }
                ],
            },
            "telemetry": {"local_compute_tflops": 24.0, "tokens_processed": 0},
        }

        agg._peer_nodes["mifcom"] = {
            "node_id": "mifcom",
            "status": "online",
            "inventory": {
                "total_vram_bytes": 16 * 1024 * 1024 * 1024,
                "gpus": [
                    {
                        "vendor": "NVIDIA",
                        "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU",
                        "vram_bytes": 16 * 1024 * 1024 * 1024,
                        "healthy": True,
                    }
                ],
            },
            "telemetry": {"local_compute_tflops": 24.0, "tokens_processed": 0},
        }

        # Compute cluster stats
        stats = agg.get_mesh_stats(local_status=local_payload)

        # Verification: Only 2 unique physical nodes exist (16GB Laptop + 8GB MI25 = 24GB Pool, NOT 56GB!)
        self.assertEqual(stats["total_nodes_online"], 2)
        self.assertEqual(stats["total_vram_gb"], 24.0)
        self.assertAlmostEqual(stats["total_compute_tflops"], 48.6, places=1)

        reported_nids = [n["node_id"] for n in stats["nodes"]]
        self.assertIn("cm-node-48GB-Miner", reported_nids)
        self.assertIn("cm-inference-node-01", reported_nids)
        self.assertNotIn("test-node-custom", reported_nids)
        self.assertNotIn("mifcom", reported_nids)

    def test_gateway_fleet_payload_deduplicates_hardware_and_tokens(self) -> None:
        """Verify _build_fleet_payload treats multiple alias entries with same token/GPU as 1 node."""
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        owner_k = "inet-test-owner-dedup-01"
        owner_id = owner_id_for_key(owner_k)
        self.assertIsNotNone(owner_id)

        token_laptop = "cm_tunnel_" + ("b" * 32)
        token_miner = "cm_tunnel_" + ("c" * 32)

        # 1. Active current laptop node
        NODE_TELEMETRY_REGISTRY["cm-node-48GB-Miner"] = {
            "node_id": "cm-node-48GB-Miner",
            "auth_token": token_laptop,
            "owner_id": owner_id,
            "client_ip": "1.2.3.4",
            "updated_at": now_iso,
            "inventory": {
                "total_vram_bytes": 16 * 1024 * 1024 * 1024,
                "gpus": [{"vendor": "nvidia", "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 24.0},
        }

        # 2. Older alias of the same laptop
        NODE_TELEMETRY_REGISTRY["test-node-custom"] = {
            "node_id": "test-node-custom",
            "auth_token": token_laptop,
            "owner_id": owner_id,
            "client_ip": "1.2.3.4",
            "updated_at": "2026-09-10T20:50:00Z",
            "inventory": {
                "total_vram_bytes": 16 * 1024 * 1024 * 1024,
                "gpus": [{"vendor": "nvidia", "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 24.0},
        }

        # 3. Third alias from the same client IP with same GPU
        NODE_TELEMETRY_REGISTRY["mifcom"] = {
            "node_id": "mifcom",
            "auth_token": "peer_relayed_mifcom",
            "is_peer_relay": True,
            "owner_id": owner_id,
            "client_ip": "1.2.3.4",
            "updated_at": "",
            "inventory": {
                "total_vram_bytes": 16 * 1024 * 1024 * 1024,
                "gpus": [{"vendor": "nvidia", "model_name": "NVIDIA GeForce RTX 3080 Laptop GPU", "vram_bytes": 16 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 24.0},
        }

        # 4. Distinct MI25 mining rig
        NODE_TELEMETRY_REGISTRY["cm-inference-node-01"] = {
            "node_id": "cm-inference-node-01",
            "auth_token": token_miner,
            "owner_id": owner_id,
            "client_ip": "5.6.7.8",
            "updated_at": now_iso,
            "inventory": {
                "total_vram_bytes": 8 * 1024 * 1024 * 1024,
                "gpus": [{"vendor": "amd", "model_name": "AMD Radeon Instinct MI25", "vram_bytes": 8 * 1024**3, "healthy": True}],
            },
            "telemetry": {"local_compute_tflops": 24.6},
        }

        OWNER_ACCOUNT_STORE.ensure_owner(owner_id)
        OWNER_ACCOUNT_STORE.bind_provider_node(owner_id, "cm-node-48GB-Miner")
        OWNER_ACCOUNT_STORE.bind_provider_node(owner_id, "test-node-custom")
        OWNER_ACCOUNT_STORE.bind_provider_node(owner_id, "cm-inference-node-01")

        fleet = _build_fleet_payload(owner_id)

        # Must be exactly 2 nodes (1x 16GB + 1x 8GB = 24GB Total VRAM, 48.6 TFLOPS)
        self.assertEqual(fleet["total_nodes_bound"], 2)
        self.assertEqual(fleet["total_vram_gb"], 24.0)
        self.assertEqual(fleet["total_tflops"], 48.6)

        returned_ids = [n["node_id"] for n in fleet["nodes"]]
        self.assertIn("cm-node-48GB-Miner", returned_ids)
        self.assertIn("cm-inference-node-01", returned_ids)
        self.assertNotIn("test-node-custom", returned_ids)
        self.assertNotIn("mifcom", returned_ids)


if __name__ == "__main__":
    unittest.main()
