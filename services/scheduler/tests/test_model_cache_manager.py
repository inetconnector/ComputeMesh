"""Unit tests for Dynamic Multi-Model Hot-Swapping Cache Manager."""
import unittest

from services.scheduler.model_cache_manager import (
    CachedModelMetadata,
    DynamicModelCacheManager,
    ModelCacheError,
)


class TestModelCacheManager(unittest.TestCase):
    def setUp(self) -> None:
        # 40 GB Rig (e.g. 5x 8GB) with 36 GB usable VRAM (90%)
        gb = 1024 * 1024 * 1024
        self.mgr = DynamicModelCacheManager(total_rig_vram_bytes=40 * gb, usable_memory_fraction=0.90)

        self.m_7b = CachedModelMetadata("qwen2.5-7b", weight_bytes=4 * gb, total_layers=32)
        self.m_14b = CachedModelMetadata("qwen2.5-14b", weight_bytes=9 * gb, total_layers=48)
        self.m_32b = CachedModelMetadata("qwen2.5-32b", weight_bytes=19 * gb, total_layers=64)
        self.m_70b = CachedModelMetadata("llama-3.1-70b", weight_bytes=40 * gb, total_layers=80)

    def test_cache_hit_and_access(self) -> None:
        res1 = self.mgr.request_model(self.m_7b, now_utc=100.0)
        self.assertEqual(res1["action"], "loaded")
        self.assertEqual(self.mgr.cache_misses, 1)

        res2 = self.mgr.request_model(self.m_7b, now_utc=105.0)
        self.assertEqual(res2["action"], "hit")
        self.assertEqual(self.mgr.cache_hits, 1)

    def test_lru_eviction_when_vram_full(self) -> None:
        # Load 7B (4GB) and 14B (9GB) and 32B (19GB) -> total 32GB <= 36GB usable
        self.mgr.request_model(self.m_7b, now_utc=100.0)
        self.mgr.release_model_inference("qwen2.5-7b")

        self.mgr.request_model(self.m_14b, now_utc=105.0)
        self.mgr.release_model_inference("qwen2.5-14b")

        self.mgr.request_model(self.m_32b, now_utc=110.0)
        self.mgr.release_model_inference("qwen2.5-32b")

        # Now try to load another 14B model (9GB) -> requires 9GB free, currently only 4GB free
        # Should evict oldest model (7B)
        m_another_14b = CachedModelMetadata("deepseek-14b", weight_bytes=9 * 1024**3, total_layers=48)
        res = self.mgr.request_model(m_another_14b, now_utc=120.0)

        self.assertEqual(res["action"], "loaded")
        self.assertIn("qwen2.5-7b", res["evicted"])
        self.assertNotIn("qwen2.5-7b", self.mgr.loaded_models)
        self.assertIn("deepseek-14b", self.mgr.loaded_models)

    def test_pinned_model_never_evicted(self) -> None:
        # Pin 7B model
        m_7b_pinned = CachedModelMetadata("qwen2.5-7b", weight_bytes=4 * 1024**3, total_layers=32, is_pinned=True)
        self.mgr.request_model(m_7b_pinned, now_utc=100.0)
        self.mgr.release_model_inference("qwen2.5-7b")

        # Load 32B (19GB)
        self.mgr.request_model(self.m_32b, now_utc=105.0)
        self.mgr.release_model_inference("qwen2.5-32b")

        # Now load another 19GB model -> must evict 32B, but NOT pinned 7B
        m_another_32b = CachedModelMetadata("qwen2.5-coder-32b", weight_bytes=19 * 1024**3, total_layers=64)
        res = self.mgr.request_model(m_another_32b, now_utc=110.0)

        self.assertIn("qwen2.5-32b", res["evicted"])
        self.assertIn("qwen2.5-7b", self.mgr.loaded_models)  # Still present because pinned

    def test_oversized_model_raises_error(self) -> None:
        # 70B model requires 40GB > 36GB usable
        with self.assertRaises(ModelCacheError):
            self.mgr.request_model(self.m_70b)


if __name__ == "__main__":
    unittest.main()
