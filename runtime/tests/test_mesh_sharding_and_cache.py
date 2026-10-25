import unittest
import json
import time
import tempfile
from pathlib import Path
from runtime.dynamic_sharding import DynamicShardingEngine, NodeShardCapability
from runtime.distributed_model_cache import DistributedModelCache, OffHeapCacheManager
from runtime.p2p_stream_federation import P2PStreamFederator

class TestDynamicShardingEngine(unittest.TestCase):
    def test_sharding_plan_calculation(self):
        nodes = [
            NodeShardCapability(node_id="node-1", vram_bytes=24 * 1024**3, tflops=35.0, is_local=True),
            NodeShardCapability(node_id="node-2", vram_bytes=16 * 1024**3, tflops=20.0, is_local=False),
        ]
        plan = DynamicShardingEngine.calculate_sharding_plan(
            model_id="Qwen/70B",
            total_layers=80,
            model_vram_bytes=32 * 1024**3,
            nodes=nodes,
        )
        self.assertTrue(plan.feasible)
        self.assertEqual(len(plan.assignments), 2)
        self.assertEqual(sum(a.assigned_layers_count for a in plan.assignments), 80)
        self.assertGreater(plan.estimated_pipeline_latency_ms, 0)

    def test_sharding_plan_insufficient_vram(self):
        nodes = [
            NodeShardCapability(node_id="node-small", vram_bytes=4 * 1024**3, tflops=10.0, is_local=True),
        ]
        plan = DynamicShardingEngine.calculate_sharding_plan(
            model_id="Qwen/70B",
            total_layers=80,
            model_vram_bytes=32 * 1024**3,
            nodes=nodes,
        )
        self.assertFalse(plan.feasible)
        self.assertIn("Insufficient total mesh VRAM", plan.reason)

    def test_tensor_parallel_sharding(self):
        nodes = [
            NodeShardCapability(node_id="node-1", vram_bytes=24 * 1024**3, tflops=35.0, is_local=True, tensor_parallel_supported=True),
            NodeShardCapability(node_id="node-2", vram_bytes=24 * 1024**3, tflops=35.0, is_local=False, tensor_parallel_supported=True),
        ]
        plan = DynamicShardingEngine.calculate_sharding_plan(
            model_id="Qwen/70B",
            total_layers=80,
            model_vram_bytes=32 * 1024**3,
            nodes=nodes,
            enable_tensor_parallel=True,
        )
        self.assertTrue(plan.feasible)
        self.assertTrue(plan.tensor_parallel_enabled)
        for assignment in plan.assignments:
            self.assertGreaterEqual(assignment.tensor_parallel_degree, 1)


class TestDistributedModelCache(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.cache = DistributedModelCache(cache_dir=self.tmpdir.name, max_cache_bytes=5000)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_cache_registration_and_eviction(self):
        chunks = [(0, b"chunk_zero_data_12345"), (1, b"chunk_one_data_67890")]
        manifest = self.cache.register_model_shard("test-model-1", total_size_bytes=2000, chunks_data=chunks)
        self.assertIsNotNone(manifest)
        self.assertEqual(len(manifest.chunks), 2)

        summary = self.cache.get_cache_summary()
        self.assertEqual(summary["total_cached_models"], 1)

        self.cache.remove_model_shard("test-model-1")
        summary_after = self.cache.get_cache_summary()
        self.assertEqual(summary_after["total_cached_models"], 0)

    def test_cache_pinning_and_integrity_verification(self):
        chunks = [(0, b"valid_chunk_bytes_001"), (1, b"valid_chunk_bytes_002")]
        self.cache.register_model_shard("pinned-model-1", total_size_bytes=2000, chunks_data=chunks, is_pinned=True)

        self.assertTrue(self.cache.pin_model_shard("pinned-model-1", True))
        integrity = self.cache.verify_shard_integrity("pinned-model-1")
        self.assertTrue(integrity["valid"])
        self.assertEqual(len(integrity["missing_chunks"]), 0)

        missing = self.cache.get_missing_chunks("pinned-model-1", 3)
        self.assertIn(2, missing)


class TestP2PStreamFederation(unittest.TestCase):
    def test_stream_federation_and_failover(self):
        federator = P2PStreamFederator()
        federator.register_peer("peer-a", transport_type="webrtc", latency_ms=12.5)

        def sample_tokens():
            yield "Hello "
            yield "world "
            yield "mesh!"

        tokens = list(federator.federate_stream("stream-123", sample_tokens, primary_peer_id="peer-a"))
        self.assertEqual(tokens, ["Hello ", "world ", "mesh!"])

        metrics = federator.get_stream_metrics("stream-123")
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["total_tokens"], 3)
        self.assertFalse(metrics["failover_occurred"])

    def test_peer_health_and_failover_sequence(self):
        federator = P2PStreamFederator()
        federator.register_peer("peer-1", transport_type="webrtc", latency_ms=8.0)
        federator.update_peer_metrics("peer-1", latency_ms=10.0, error_rate=0.01)

        health = federator.get_peer_health()
        self.assertEqual(len(health), 1)
        self.assertEqual(health[0]["peer_id"], "peer-1")
        self.assertTrue(health[0]["is_active"])

        def failing_tokens():
            yield "Token 1 "
            raise RuntimeError("Peer network disconnected")

        tokens = list(federator.federate_stream("stream-456", failing_tokens, primary_peer_id="peer-1", fallback_peer_id="peer-2"))
        self.assertIn("Token 1 ", tokens[0])
        self.assertIn("Failover to peer-2", tokens[1])

        metrics = federator.get_stream_metrics("stream-456")
        self.assertTrue(metrics["failover_occurred"])
        self.assertEqual(metrics["active_peer_id"], "peer-2")


class TestOffHeapCacheManager(unittest.TestCase):
    def test_allocate_and_read(self):
        manager = OffHeapCacheManager(max_quota_bytes=1024 * 1024) # 1MB quota

        # Test basic allocation
        data = b"hello_off_heap"
        success = manager.allocate_chunk("chunk_1", data)
        self.assertTrue(success)
        self.assertEqual(manager.get_used_quota(), len(data))

        # Test read
        read_data = manager.read_chunk("chunk_1")
        self.assertEqual(read_data, data)

        # Test atomic quota enforcement
        large_data = b"A" * (1024 * 1024)
        success_large = manager.allocate_chunk("chunk_2", large_data)
        self.assertFalse(success_large) # Should fail due to quota
        self.assertEqual(manager.get_used_quota(), len(data)) # Quota unchanged

        # Test free
        manager.free_chunk("chunk_1")
        self.assertEqual(manager.get_used_quota(), 0)
        self.assertIsNone(manager.read_chunk("chunk_1"))


if __name__ == "__main__":
    unittest.main()
