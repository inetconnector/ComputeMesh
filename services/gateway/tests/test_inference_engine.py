"""Unit tests for ComputeMesh InferenceEngine & Streaming Protocol Converters."""
import json
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import InsufficientBalanceError, Ledger
from services.gateway.inference import InferenceEngine
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.teaser import TeaserQuotaManager


class TestInferenceEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.metrics = MetricsRegistry()
        self.teaser_manager = TeaserQuotaManager(max_requests=10, max_tokens=5000)
        self.engine = InferenceEngine(
            ledger=self.ledger,
            metrics=self.metrics,
            teaser_manager=self.teaser_manager,
        )
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_test_infer",
            amount_micro_units=50_000_000,
            payment_reference="test_init",
        )

    def test_execute_chat_completion_success(self) -> None:
        res, err, status = self.engine.execute_chat_completion(
            account_id="cust_test_infer",
            model_id="qwen/qwen2.5-7b-instruct",
            messages=[{"role": "user", "content": "Explain decentralized compute"}],
        )
        self.assertIsNone(err)
        self.assertEqual(status, 200)
        self.assertIsNotNone(res)
        self.assertTrue(res["id"].startswith("chatcmpl-"))
        self.assertEqual(res["model"], "qwen/qwen2.5-7b-instruct")
        self.assertEqual(res["choices"][0]["message"]["role"], "assistant")
        self.assertIn("ComputeMesh distributed response", res["choices"][0]["message"]["content"])
        self.assertGreater(res["usage"]["total_tokens"], 0)

    def test_execute_chat_completion_insufficient_balance(self) -> None:
        res, err, status = self.engine.execute_chat_completion(
            account_id="cust_empty_wallet",
            model_id="qwen/qwen2.5-7b-instruct",
            messages=[{"role": "user", "content": "Should fail"}],
        )
        self.assertIsNotNone(err)
        self.assertEqual(status, 402)
        self.assertIsNone(res)

    def test_stream_chat_completions_sse(self) -> None:
        chunks = list(self.engine.stream_chat_completions(
            account_id="cust_test_infer",
            model_id="qwen/qwen2.5-7b-instruct",
            messages=[{"role": "user", "content": "Stream this"}],
        ))
        self.assertGreater(len(chunks), 1)
        full_text = b"".join(chunks).decode("utf-8")
        self.assertIn("data: ", full_text)
        self.assertIn("data: [DONE]", full_text)

    def test_execute_ollama_chat_and_generate(self) -> None:
        chat_res, _, _ = self.engine.execute_ollama_chat(
            account_id="cust_test_infer",
            model_id="qwen2.5:7b",
            messages=[{"role": "user", "content": "Hello Ollama"}],
        )
        self.assertIsNotNone(chat_res)
        self.assertTrue(chat_res["done"])
        self.assertEqual(chat_res["message"]["role"], "assistant")

        gen_res, _, _ = self.engine.execute_ollama_generate(
            account_id="cust_test_infer",
            model_id="llama3.1:8b",
            prompt="Generate a poem",
        )
        self.assertIsNotNone(gen_res)
        self.assertTrue(gen_res["done"])
        self.assertIn("ComputeMesh distributed response", gen_res["response"])


if __name__ == "__main__":
    unittest.main()
