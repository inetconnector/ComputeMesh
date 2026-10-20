import unittest
import json
import time
from pathlib import Path
from runtime.dynamic_sharding import DynamicShardingEngine, NodeShardCapability
from runtime.distributed_model_cache import DistributedModelCache
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


class TestDistributedModelCache(unittest.TestCase):
    def test_cache_registration_and_eviction(self):
        cache = DistributedModelCache(max_cache_bytes=5000)
        chunks = [(0, b"chunk_zero_data_12345"), (1, b"chunk_one_data_67890")]
        manifest = cache.register_model_shard("test-model-1", total_size_bytes=2000, chunks_data=chunks)
        self.assertIsNotNone(manifest)
        self.assertEqual(len(manifest.chunks), 2)

        summary = cache.get_cache_summary()
        self.assertEqual(summary["total_cached_models"], 1)

        cache.remove_model_shard("test-model-1")
        summary_after = cache.get_cache_summary()
        self.assertEqual(summary_after["total_cached_models"], 0)


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


if __name__ == "__main__":
    unittest.main()
