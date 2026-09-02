"""Tests for unified owner inference accounting."""
from pathlib import Path
import tempfile
import unittest

from services.billing.ledger import BillingError, InsufficientBalanceError
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.common.pricing import calculate_token_charge_micro
from services.gateway.inference_backend import BackendResult
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.owner_inference import UnifiedOwnerInferenceEngine
from services.gateway.teaser import TeaserQuotaManager


MODEL = "qwen/qwen2.5-7b-instruct"


class FixedBackend:
    def __init__(self, provider_shares: tuple[tuple[str, float], ...]) -> None:
        self.provider_shares = provider_shares

    def complete(self, *, model_id, messages, max_tokens=None):
        return BackendResult(
            text="ok",
            prompt_tokens=1000,
            completion_tokens=1000,
            execution_job_id="job-fixed",
            provider_shares=self.provider_shares,
        )


class TestUnifiedOwnerInference(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.ledger = GatewayOwnerCreditLedger(storage_path=root / "ledger.jsonl")
        self.owners = OwnerAccountStore(root / "owners.sqlite3")
        self.owners.ensure_owner("alice")
        self.owners.ensure_owner("bob")
        self.metrics = MetricsRegistry()
        self.teaser = TeaserQuotaManager(max_requests=5, max_tokens=10000)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _engine(self, shares, *, promo_cap=0):
        return UnifiedOwnerInferenceEngine(
            ledger=self.ledger,
            owner_account_store=self.owners,
            metrics=self.metrics,
            teaser_manager=self.teaser,
            backend=FixedBackend(tuple(shares)),
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,
            promo_foreign_cap_micro_units=promo_cap,
        )

    def _gross(self) -> int:
        return calculate_token_charge_micro(
            model_id=MODEL,
            prompt_tokens=1000,
            completion_tokens=1000,
        )

    def test_self_compute_spends_only_infrastructure_fee_and_can_use_promo(self) -> None:
        self.owners.bind_provider_node("alice", "alice-rig")
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            grant_reference="alice-promo",
            policy_version="onboarding-v1",
        )
        before = self.ledger.get_owner_balances("alice").promo_micro_units
        engine = self._engine([("alice-rig", 1.0)])
        engine.create_metered_completion(
            account_id="alice",
            model_id=MODEL,
            messages=[{"role": "user", "content": "hello"}],
            is_provider_self_compute=True,
            max_tokens=1000,
        )
        gross = self._gross()
        expected_fee = max(1, gross * 1000 // 10000)
        after = self.ledger.get_owner_balances("alice").promo_micro_units
        self.assertEqual(before - after, expected_fee)
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), expected_fee)
        self.assertEqual(self.ledger.get_owner_balances("alice").earned_micro_units, 0)

    def test_foreign_compute_creates_earned_credit_for_provider_owner(self) -> None:
        self.owners.bind_provider_node("bob", "bob-rig")
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            payment_reference="alice-purchase",
        )
        engine = self._engine([("bob-rig", 1.0)])
        engine.create_metered_completion(
            account_id="alice",
            model_id=MODEL,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=1000,
        )
        gross = self._gross()
        expected_fee = max(1, gross * 2500 // 10000)
        expected_earned = gross - expected_fee
        self.assertEqual(
            self.ledger.get_owner_balances("bob").earned_micro_units,
            expected_earned,
        )
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), expected_fee)

    def test_promo_only_cannot_fund_foreign_provider_by_default(self) -> None:
        self.owners.bind_provider_node("bob", "bob-rig")
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            grant_reference="alice-promo",
            policy_version="onboarding-v1",
        )
        before = self.ledger.get_owner_balances("alice").promo_micro_units
        engine = self._engine([("bob-rig", 1.0)], promo_cap=0)
        with self.assertRaises(InsufficientBalanceError):
            engine.create_metered_completion(
                account_id="alice",
                model_id=MODEL,
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=1000,
            )
        self.assertEqual(self.ledger.get_owner_balances("alice").promo_micro_units, before)
        self.assertEqual(self.ledger.get_owner_balances("bob").earned_micro_units, 0)
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 0)
        self.assertEqual(
            self.ledger.get_owner_balances("alice").available_spendable_micro_units,
            before,
        )

    def test_mixed_job_requires_nonpromo_coverage_for_foreign_gross(self) -> None:
        self.owners.bind_provider_node("alice", "alice-rig")
        self.owners.bind_provider_node("bob", "bob-rig")
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            payment_reference="alice-purchase",
        )
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            grant_reference="alice-promo",
            policy_version="onboarding-v1",
        )
        engine = self._engine([("alice-rig", 0.7), ("bob-rig", 0.3)])
        engine.create_metered_completion(
            account_id="alice",
            model_id=MODEL,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=1000,
        )
        self.assertGreater(self.ledger.get_owner_balances("bob").earned_micro_units, 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_unknown_provider_owner_fails_closed_without_charging_or_crediting(self) -> None:
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            payment_reference="alice-purchase",
        )
        before = self.ledger.get_owner_balances("alice").purchased_micro_units
        engine = self._engine([("orphan-rig", 1.0)])
        with self.assertRaises(BillingError):
            engine.create_metered_completion(
                account_id="alice",
                model_id=MODEL,
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=1000,
            )
        self.assertEqual(self.ledger.get_owner_balances("alice").purchased_micro_units, before)
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 0)


if __name__ == "__main__":
    unittest.main()
