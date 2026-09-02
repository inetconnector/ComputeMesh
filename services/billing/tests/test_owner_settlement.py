"""Tests for owner-level Stripe payout identity and crash-safe settlement."""
from pathlib import Path
import tempfile
import unittest

from services.billing.accounting import AccountingStore, AccountingStoreError
from services.billing.ledger import BillingError
from services.billing.owner_settlement import (
    OwnerPayoutProfileStore,
    OwnerSettlementExecutor,
    PayoutCapableOwnerLedger,
)
from services.billing.stripe_connect import ConnectedAccountResult, StripeConnectService
from services.billing.stripe_integration import StripeIntegrationError


class FakeOwnerStripe:
    def __init__(self) -> None:
        self.fail_transfer = False
        self.transfer_calls: list[dict] = []

    def retrieve_connected_account(self, *, owner_id: str, stripe_connected_account_id: str):
        return ConnectedAccountResult(
            provider_node_id=f"owner:{owner_id}",
            stripe_connected_account_id=stripe_connected_account_id,
            onboarding_status="ready",
            charges_enabled=False,
            payouts_enabled=True,
            details_submitted=True,
        )

    def transfer(self, **kwargs):
        self.transfer_calls.append(dict(kwargs))
        if self.fail_transfer:
            raise StripeIntegrationError("simulated ambiguous network timeout")
        return "tr_owner_123"


class TestOwnerSettlement(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.ledger = PayoutCapableOwnerLedger(storage_path=self.root / "ledger.jsonl")
        self.account_store = AccountingStore(self.root / "accounting.sqlite3")
        self.executor = OwnerSettlementExecutor(
            ledger=self.ledger,
            account_store=self.account_store,
            stripe_connect=StripeConnectService(),
        )
        self.fake_stripe = FakeOwnerStripe()
        self.executor.stripe = self.fake_stripe  # type: ignore[assignment]
        self.executor.profile_store.attach_stripe_account(
            owner_id="alice",
            stripe_connected_account_id="acct_owner_alice",
            onboarding_status="ready",
        )
        self.executor.profile_store.update_status(
            owner_id="alice",
            onboarding_status="ready",
            payouts_enabled=True,
            details_submitted=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _earn(self, amount: int) -> None:
        self.ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=amount,
            earning_reference=f"earning-{amount}-{len(self.ledger._transactions)}",
        )

    def test_reserve_and_finalize_moves_only_earned_liability(self) -> None:
        self._earn(40_000_000)
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=50_000_000,
            payment_reference="purchase-1",
        )
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=25_000_000,
            grant_reference="promo-1",
            policy_version="test-v1",
        )

        self.ledger.reserve_owner_withdrawal(
            owner_id="alice",
            amount_micro_units=30_000_000,
            settlement_reference="settle-1",
        )
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.earned_micro_units, 10_000_000)
        self.assertEqual(balances.purchased_micro_units, 50_000_000)
        self.assertEqual(balances.promo_micro_units, 25_000_000)
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 30_000_000)

        self.ledger.finalize_owner_withdrawal(
            owner_id="alice",
            amount_micro_units=30_000_000,
            settlement_reference="settle-1",
        )
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 0)
        self.assertEqual(self.ledger.get_owner_balances("alice").earned_micro_units, 10_000_000)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_cancel_reservation_restores_earned(self) -> None:
        self._earn(30_000_000)
        self.ledger.reserve_owner_withdrawal(
            owner_id="alice",
            amount_micro_units=25_000_000,
            settlement_reference="cancel-me",
        )
        self.ledger.cancel_owner_withdrawal(
            owner_id="alice",
            amount_micro_units=25_000_000,
            settlement_reference="cancel-me",
        )
        self.assertEqual(self.ledger.get_owner_balances("alice").earned_micro_units, 30_000_000)
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_purchased_and_promo_are_never_withdrawable(self) -> None:
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=100_000_000,
            payment_reference="purchase-only",
        )
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=100_000_000,
            grant_reference="promo-only",
            policy_version="test-v1",
        )
        with self.assertRaises(BillingError):
            self.executor.run_owner_settlement(owner_id="alice")
        self.assertEqual(self.ledger.owner_withdrawable_micro_units("alice"), 0)

    def test_successful_owner_settlement_quantizes_to_stripe_cent_precision(self) -> None:
        self._earn(40_125_678)
        settlement = self.executor.run_owner_settlement(
            owner_id="alice",
            amount_micro_units=30_125_678,
            settlement_reference="withdraw-precision",
        )
        self.assertEqual(settlement.status, "completed")
        self.assertEqual(settlement.amount_micro_units, 30_120_000)
        self.assertEqual(settlement.stripe_transfer_id, "tr_owner_123")
        self.assertEqual(self.fake_stripe.transfer_calls[0]["amount_micro_units"], 30_120_000)
        self.assertEqual(self.ledger.get_owner_balances("alice").earned_micro_units, 10_005_678)
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_ambiguous_transfer_failure_stays_reserved_and_retry_is_idempotent(self) -> None:
        self._earn(30_000_000)
        self.fake_stripe.fail_transfer = True
        first = self.executor.run_owner_settlement(
            owner_id="alice",
            settlement_reference="timeout-retry",
        )
        self.assertEqual(first.status, "pending_retry")
        self.assertEqual(self.ledger.get_owner_balances("alice").earned_micro_units, 0)
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 30_000_000)
        self.assertEqual(len(self.fake_stripe.transfer_calls), 1)

        self.fake_stripe.fail_transfer = False
        second = self.executor.run_owner_settlement(owner_id="alice")
        self.assertEqual(second.status, "completed")
        self.assertEqual(second.settlement_id, first.settlement_id)
        self.assertEqual(len(self.fake_stripe.transfer_calls), 2)
        self.assertEqual(
            self.fake_stripe.transfer_calls[0]["settlement_id"],
            self.fake_stripe.transfer_calls[1]["settlement_id"],
        )
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_one_stripe_account_cannot_be_shared_by_two_owners(self) -> None:
        profiles = OwnerPayoutProfileStore(self.account_store)
        profiles.attach_stripe_account(
            owner_id="bob",
            stripe_connected_account_id="acct_unique",
        )
        with self.assertRaises(AccountingStoreError):
            profiles.attach_stripe_account(
                owner_id="charlie",
                stripe_connected_account_id="acct_unique",
            )


if __name__ == "__main__":
    unittest.main()
