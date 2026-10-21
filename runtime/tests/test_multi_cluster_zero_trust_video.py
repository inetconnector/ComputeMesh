"""Unit tests for Multi-Cluster Federation, Zero-Trust Worker Communication, and Adaptive Video Stream Compression."""
from __future__ import annotations

import time
import unittest

from runtime.multi_cluster_federation import (
    ClusterNode,
    MultiClusterFederator,
)
from runtime.zero_trust_worker import (
    ZeroTrustWorkerCommunicator,
)
from runtime.adaptive_video_compression import (
    AdaptiveVideoCompressor,
)


class TestMultiClusterFederation(unittest.TestCase):
    def setUp(self) -> None:
        self.federator = MultiClusterFederator()

    def test_cluster_registration_and_capacity(self) -> None:
        cluster = self.federator.register_cluster(
            cluster_id="cluster-us-east",
            name="US East Cluster",
            region="us-east",
            nodes=[
                ClusterNode(
                    node_id="node-us-1",
                    cluster_id="cluster-us-east",
                    vram_bytes=32 * 1024 * 1024 * 1024,
                    tflops=80.0,
                    region="us-east",
                    is_active=True,
                )
            ],
        )
        self.assertEqual(cluster.cluster_id, "cluster-us-east")
        self.assertEqual(cluster.total_vram_bytes, 32 * 1024 * 1024 * 1024)

        capacity = self.federator.get_federated_capacity()
        self.assertGreaterEqual(capacity["total_clusters"], 2)
        self.assertIn("cluster-us-east", [c["cluster_id"] for c in capacity["clusters"]])

    def test_update_node_health_and_score(self) -> None:
        self.federator.register_cluster(
            cluster_id="cluster-asia",
            name="Asia Pacific Cluster",
            region="asia-south",
            nodes=[
                ClusterNode(
                    node_id="node-asia-1",
                    cluster_id="cluster-asia",
                    vram_bytes=16 * 1024 * 1024 * 1024,
                    tflops=40.0,
                    is_active=True,
                )
            ],
        )
        res = self.federator.update_node_health("cluster-asia", "node-asia-1", ping_ms=25.0, is_active=True)
        self.assertTrue(res)
        cluster = self.federator._clusters["cluster-asia"]
        self.assertEqual(cluster.nodes["node-asia-1"].ping_ms, 25.0)

    def test_sync_cluster_states(self) -> None:
        payloads = [
            {
                "cluster_id": "cluster-remote-1",
                "name": "Remote Cluster 1",
                "region": "eu-west",
                "nodes": [
                    {
                        "node_id": "remote-node-1",
                        "vram_bytes": 24 * 1024 * 1024 * 1024,
                        "tflops": 50.0,
                        "ping_ms": 15.0,
                        "is_active": True,
                    }
                ],
            }
        ]
        synced = self.federator.sync_cluster_states(payloads)
        self.assertEqual(synced, 1)
        self.assertIn("cluster-remote-1", self.federator._clusters)

    def test_cross_cluster_sharding_plan(self) -> None:
        plan = self.federator.calculate_cross_cluster_plan(
            model_id="Qwen/Qwen2.5-72B-Instruct-GGUF",
            total_layers=80,
            model_vram_bytes=20 * 1024 * 1024 * 1024,
        )
        self.assertTrue(plan["feasible"])
        self.assertGreater(len(plan["cluster_assignments"]), 0)


class TestZeroTrustWorkerCommunication(unittest.TestCase):
    def setUp(self) -> None:
        self.zt = ZeroTrustWorkerCommunicator(hmac_secret="test-secret-key-123", nonce_window_seconds=5.0)

    def test_handshake_and_session_creation(self) -> None:
        session = self.zt.initiate_worker_handshake(
            worker_id="worker-02",
            cluster_id="cluster-primary",
            client_cert_cn="node-worker-02.mesh.local",
            auth_token="valid-secret-token-12345",
        )
        self.assertTrue(session.verified)
        self.assertFalse(session.is_isolated)
        self.assertIn(session.session_id, self.zt._sessions)

    def test_payload_signing_and_verification(self) -> None:
        session = self.zt.initiate_worker_handshake(
            worker_id="worker-03",
            cluster_id="cluster-primary",
            client_cert_cn="node-worker-03.mesh.local",
            auth_token="valid-secret-token-12345",
        )
        payload = b"activation_tensor_data_bytes_12345"
        signed = self.zt.sign_payload(session.session_id, payload)

        verified = self.zt.verify_payload(
            session_id=session.session_id,
            payload_bytes=payload,
            signature=signed["signature"],
            nonce=signed["nonce"],
            timestamp=signed["timestamp"],
        )
        self.assertTrue(verified)

    def test_replay_attack_detection_and_quarantine(self) -> None:
        session = self.zt.initiate_worker_handshake(
            worker_id="worker-04",
            cluster_id="cluster-primary",
            client_cert_cn="node-worker-04.mesh.local",
            auth_token="valid-secret-token-12345",
        )
        payload = b"payload_bytes"
        signed = self.zt.sign_payload(session.session_id, payload)

        # First verification succeeds
        v1 = self.zt.verify_payload(
            session.session_id, payload, signed["signature"], signed["nonce"], signed["timestamp"]
        )
        self.assertTrue(v1)

        # Replaying same nonce triggers quarantine
        v2 = self.zt.verify_payload(
            session.session_id, payload, signed["signature"], signed["nonce"], signed["timestamp"]
        )
        self.assertFalse(v2)
        self.assertTrue(session.is_isolated)
        self.assertIn("worker-04", self.zt._isolated_workers)

    def test_payload_tampering_detection(self) -> None:
        session = self.zt.initiate_worker_handshake(
            worker_id="worker-05",
            cluster_id="cluster-primary",
            client_cert_cn="node-worker-05.mesh.local",
            auth_token="valid-secret-token-12345",
        )
        payload = b"original_payload"
        signed = self.zt.sign_payload(session.session_id, payload)

        tampered_payload = b"tampered_payload"
        verified = self.zt.verify_payload(
            session.session_id, tampered_payload, signed["signature"], signed["nonce"], signed["timestamp"]
        )
        self.assertFalse(verified)
        self.assertTrue(session.is_isolated)


class TestAdaptiveVideoCompression(unittest.TestCase):
    def setUp(self) -> None:
        self.compressor = AdaptiveVideoCompressor()

    def test_evaluate_network_conditions(self) -> None:
        p_ultra = self.compressor.evaluate_network_conditions(rtt_ms=10.0, packet_loss_pct=0.1, bandwidth_kbps=10000)
        self.assertEqual(p_ultra.tier_name, "ultra_hd")

        p_low = self.compressor.evaluate_network_conditions(rtt_ms=180.0, packet_loss_pct=8.0, bandwidth_kbps=800)
        self.assertEqual(p_low.tier_name, "low_bandwidth")

        p_bad = self.compressor.evaluate_network_conditions(rtt_ms=400.0, packet_loss_pct=15.0, bandwidth_kbps=200)
        self.assertEqual(p_bad.tier_name, "ultra_compressed")

    def test_compress_and_decompress_frame_tokens(self) -> None:
        raw_frame = b"visual_frame_data_token_stream_" * 100
        compressed = self.compressor.compress_frame_tokens(raw_frame)
        self.assertLess(len(compressed), len(raw_frame))

        decompressed = self.compressor.decompress_frame_tokens(compressed)
        self.assertEqual(decompressed, raw_frame)

    def test_compression_metrics(self) -> None:
        raw_frame = b"frame_bytes_" * 50
        self.compressor.compress_frame_tokens(raw_frame)
        metrics = self.compressor.get_compression_metrics()

        self.assertEqual(metrics["status"], "active")
        self.assertGreater(metrics["processed_frames_count"], 0)
        self.assertGreater(metrics["bandwidth_savings_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
