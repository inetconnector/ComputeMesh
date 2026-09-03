from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.gateway.cancellable_owner_inference import CancellableUnifiedOwnerInferenceEngine
from services.gateway.inference_backend import BackendResult
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.teaser import TeaserQuotaManager


MODEL = "qwen/qwen2.5-7b-instruct"


class RequestAwareBackend:
    def __init__(self) -> None:
        self.request_ids: list[str] = []
        self.cancelled: list[str] = []

    def complete_for_request(self, *, request_id, model_id, messages, max_tokens=None):
        self.request_ids.append(request_id)
        return BackendResult(
            text="ok",
            prompt_tokens=100,
            completion_tokens=50,
            execution_job_id=f"job-{request_id}",
            provider_shares=(("bob-rig", 1.0),),
        )

    def complete(self, *, model_id, messages, max_tokens=None):
        raise AssertionError("request-scoped live backend path should be used")

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


class CancellableOwnerInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.ledger = GatewayOwnerCreditLedger(storage_path=root / "ledger.jsonl")
        self.owners = OwnerAccountStore(root / "owners.sqlite3")
        self.owners.ensure_owner("alice")
        self.owners.ensure_owner("bob")
        self.owners.bind_provider_node("bob", "bob-rig")
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            payment_reference="seed",
        )
        self.backend = RequestAwareBackend()
        self.engine = CancellableUnifiedOwnerInferenceEngine(
            ledger=self.ledger,
            owner_account_store=self.owners,
            metrics=MetricsRegistry(),
            teaser_manager=TeaserQuotaManager(max_requests=5, max_tokens=10000),
            backend=self.backend,
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_request_scope_uses_live_request_id_and_preserves_owner_settlement(self) -> None:
        with self.engine.request_scope("req-123"):
            self.engine.create_metered_completion(
                account_id="alice",
                model_id=MODEL,
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=64,
            )
        self.assertEqual(self.backend.request_ids, ["req-123"])
        self.assertGreater(self.ledger.get_owner_balances("bob").earned_micro_units, 0)
        self.assertGreater(self.ledger.get_balance("revenue:network_fee"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_cancel_is_owner_scoped(self) -> None:
        self.engine._active_owners["req-active"] = "alice"
        self.assertFalse(
            self.engine.cancel_request(account_id="mallory", request_id="req-active")
        )
        self.assertTrue(
            self.engine.cancel_request(account_id="alice", request_id="req-active")
        )
        self.assertEqual(self.backend.cancelled, ["req-active"])

    def test_invalid_request_id_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            with self.engine.request_scope("bad request id"):
                pass


if __name__ == "__main__":
    unittest.main()
