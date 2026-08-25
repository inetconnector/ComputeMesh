"""Unit tests for ComputeMesh Gateway Catalog & Pricing Specifications."""
import os
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.gateway.catalog import (
    AVAILABLE_MODELS,
    DEFAULT_PRICE_TIERS,
    ModelSpec,
    PriceTier,
    provider_shares_from_env,
    resolve_model_id,
)


class TestCatalogAndPricing(unittest.TestCase):
    def test_available_models_catalog_integrity(self) -> None:
        self.assertGreaterEqual(len(AVAILABLE_MODELS), 5)
        model_ids = {m.id for m in AVAILABLE_MODELS}
        self.assertIn("qwen/qwen2.5-7b-instruct", model_ids)
        self.assertIn("meta-llama/llama-3.1-8b-instruct", model_ids)
        self.assertIn("deepseek-ai/deepseek-r1", model_ids)

        for m in AVAILABLE_MODELS:
            self.assertIsInstance(m, ModelSpec)
            self.assertGreater(m.context_window, 0)
            self.assertIsInstance(m.price_tier, PriceTier)
            self.assertGreaterEqual(m.price_tier.prompt_micro_per_token, 0)
            self.assertGreater(m.price_tier.completion_micro_per_token, 0)

    def test_resolve_model_id_aliases(self) -> None:
        # Exact match
        self.assertEqual(resolve_model_id("qwen/qwen2.5-7b-instruct"), "qwen/qwen2.5-7b-instruct")

        # Ollama style tags
        self.assertEqual(resolve_model_id("qwen2.5:7b"), "qwen/qwen2.5-7b-instruct")
        self.assertEqual(resolve_model_id("llama3.1:8b"), "meta-llama/llama-3.1-8b-instruct")
        self.assertEqual(resolve_model_id("llama3.3:70b"), "meta-llama/llama-3.3-70b-instruct")
        self.assertEqual(resolve_model_id("deepseek-r1"), "deepseek-ai/deepseek-r1")

        # Fallback to default
        self.assertEqual(resolve_model_id(""), "qwen/qwen2.5-7b-instruct")
        self.assertEqual(resolve_model_id("unknown_future_model"), "qwen/qwen2.5-7b-instruct")

    def test_provider_shares_from_env_default(self) -> None:
        old_env = os.environ.pop("COMPUTEMESH_PROVIDER_SHARES", None)
        try:
            shares = provider_shares_from_env()
            self.assertEqual(len(shares), 1)
            self.assertEqual(shares[0][1], 1.0)
        finally:
            if old_env is not None:
                os.environ["COMPUTEMESH_PROVIDER_SHARES"] = old_env

    def test_provider_shares_from_env_multi_node(self) -> None:
        os.environ["COMPUTEMESH_PROVIDER_SHARES"] = "node_a:0.6,node_b:0.4"
        try:
            shares = provider_shares_from_env()
            self.assertEqual(len(shares), 2)
            self.assertEqual(shares[0], ("node_a", 0.6))
            self.assertEqual(shares[1], ("node_b", 0.4))
        finally:
            os.environ.pop("COMPUTEMESH_PROVIDER_SHARES", None)


if __name__ == "__main__":
    unittest.main()
