from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.billing.ledger import Ledger
from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import BackendResult
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.teaser import TeaserQuotaManager


class _VerifiedBackend:
    def complete(self, *, model_id, messages):
        return BackendResult(
            text="verified distributed output",
            prompt_tokens=10_000,
            completion_tokens=10_000,
            execution_job_id="job-verified-001",
            provider_shares=(("node-a", 0.25), ("node-b", 0.75)),
            evidence_id="shared-run-evidence-0123456789abcdef",
        )


class VerifiedSettlementTests(unittest.TestCase):
    def test_verified_backend_shares_override_environment_and_use_orchestrator_job_id(self):
        ledger = Ledger(network_fee_bps=2500)
        ledger.deposit_customer_credits(
            customer_account_id="customer",
            amount_micro_units=1_000_000,
            payment_reference="verified-settlement",
        )
        engine = InferenceEngine(
            ledger=ledger,
            metrics=MetricsRegistry(),
            teaser_manager=TeaserQuotaManager(max_requests=5, max_tokens=1000),
            backend=_VerifiedBackend(),
        )
        with patch.dict(
            os.environ,
            {"COMPUTEMESH_PROVIDER_SHARES": "wrong-node:1.0"},
            clear=False,
        ):
            engine.create_metered_completion(
                account_id="customer",
                model_id="qwen/qwen2.5-7b-instruct",
                messages=[{"role": "user", "content": "hello"}],
            )

        # 20 tokens * 200 micro = 4,000 total; 25% fee leaves 3,000 provider pool.
        self.assertEqual(ledger.get_balance("provider:node-a"), 750)
        self.assertEqual(ledger.get_balance("provider:node-b"), 2250)
        self.assertEqual(ledger.get_balance("provider:wrong-node"), 0)
        billed = [tx for tx in ledger._transactions if tx.event_id == "job:job-verified-001"]
        self.assertEqual(len(billed), 1)


if __name__ == "__main__":
    unittest.main()
