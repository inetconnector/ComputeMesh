"""Regression tests for hardened owner settlement replay/recovery semantics."""
from pathlib import Path
import tempfile
import unittest

from services.billing.accounting import AccountingStore, AccountingStoreError, SettlementRecord, utc_now
from services.billing.ledger import InsufficientBalanceError
from services.billing.owner_settlement import PayoutCapableOwnerLedger
from services.billing.owner_settlement_runtime import RobustOwnerSettlementExecutor
from services.billing.stripe_connect import ConnectedAccountResult, StripeConnectService
from services.billing.stripe_integration import StripeIntegrationError


class FakeOwnerStripe:
    def __init__(self) -> None:
        self.fail_transfer = False
        self.calls: list[dict] = []

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
        self.calls.append(dict(kwargs))
        if self.fail_transfer:
            raise StripeIntegrationError("timeout with ambiguous remote outcome")
        return "tr_runtime_1"


class TestRobustOwnerSettlement(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.ledger = PayoutCapableOwnerLedger(storage_path=root / "ledger.jsonl")
        self.accounts = AccountingStore(root / "accounting.sqlite3")
        self.executor = RobustOwnerSettlementExecutor(
            ledger=self.ledger,
            account_store=self.accounts,
            stripe_connect=StripeConnectService(),
        )
        self.fake = FakeOwnerStripe()
        self.executor.stripe = self.fake  # type: ignore[assignment]
        self.executor.profile_store.attach_stripe_account(
            owner_id="alice",
            stripe_connected_account_id="acct_alice",
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

    def _earn(self, amount: int, ref: str) -> None:
        self.ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=amount,
            earning_reference=ref,
        )

    def test_explicit_request_above_withdrawable_fails_instead_of_partial_payout(self) -> None:
        self._earn(30_000_000, "earn-a")
        with self.assertRaises(InsufficientBalanceError):
            self.executor.run_owner_settlement(
                owner_id="alice",
                amount_micro_units=40_000_000,
                settlement_reference="too-large",
            )
        self.assertEqual(self.ledger.owner_withdrawable_micro_units("alice"), 30_000_000)
        self.assertEqual(self.fake.calls, [])

    def test_completed_reference_is_idempotent_and_not_reopened(self) -> None:
        self._earn(60_000_000, "earn-b")
        first = self.executor.run_owner_settlement(
            owner_id="alice",
            amount_micro_units=30_000_000,
            settlement_reference="stable-reference",
        )
        self.assertEqual(first.status, "completed")
        self.assertEqual(len(self.fake.calls), 1)

        second = self.executor.run_owner_settlement(
            owner_id="alice",
            amount_micro_units=30_000_000,
            settlement_reference="stable-reference",
        )
        self.assertEqual(second.status, "completed")
        self.assertEqual(second.settlement_id, first.settlement_id)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.ledger.owner_withdrawable_micro_units("alice"), 30_000_000)

        with self.assertRaises(AccountingStoreError):
            self.executor.run_owner_settlement(
                owner_id="alice",
                amount_micro_units=40_000_000,
                settlement_reference="stable-reference",
            )

    def test_pending_retry_cannot_be_cancelled_into_spendable_money(self) -> None:
        self._earn(30_000_000, "earn-c")
        self.fake.fail_transfer = True
        pending = self.executor.run_owner_settlement(
            owner_id="alice",
            settlement_reference="ambiguous",
        )
        self.assertEqual(pending.status, "pending_retry")
        self.assertEqual(self.ledger.owner_withdrawable_micro_units("alice"), 0)
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 30_000_000)
        with self.assertRaises(AccountingStoreError):
            self.executor.cancel_untransferred_settlement(
                settlement_id=pending.settlement_id
            )
        self.assertEqual(self.ledger.owner_withdrawable_micro_units("alice"), 0)

    def test_crash_after_reserve_before_sql_state_update_recovers(self) -> None:
        self._earn(30_000_000, "earn-d")
        settlement_id = self.executor._settlement_id("crash-reserve")
        now = utc_now()
        self.accounts.upsert_settlement(
            SettlementRecord(
                settlement_id=settlement_id,
                account_kind="owner",
                account_id="alice",
                amount_micro_units=30_000_000,
                amount_usd=30.0,
                stripe_connected_account_id="acct_alice",
                destination="acct_alice",
                status="reserving",
                created_at=now,
                updated_at=now,
            )
        )
        self.ledger.reserve_owner_withdrawal(
            owner_id="alice",
            amount_micro_units=30_000_000,
            settlement_reference=settlement_id,
        )

        recovered = self.executor.run_owner_settlement(
            owner_id="alice",
            settlement_reference="crash-reserve",
        )
        self.assertEqual(recovered.status, "completed")
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_cancel_reserving_state_reverses_hidden_reservation(self) -> None:
        self._earn(30_000_000, "earn-e")
        settlement_id = self.executor._settlement_id("cancel-reserve-crash")
        now = utc_now()
        self.accounts.upsert_settlement(
            SettlementRecord(
                settlement_id=settlement_id,
                account_kind="owner",
                account_id="alice",
                amount_micro_units=30_000_000,
                amount_usd=30.0,
                stripe_connected_account_id="acct_alice",
                destination="acct_alice",
                status="reserving",
                created_at=now,
                updated_at=now,
            )
        )
        self.ledger.reserve_owner_withdrawal(
            owner_id="alice",
            amount_micro_units=30_000_000,
            settlement_reference=settlement_id,
        )
        cancelled = self.executor.cancel_untransferred_settlement(
            settlement_id=settlement_id
        )
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(self.ledger.owner_withdrawable_micro_units("alice"), 30_000_000)
        self.assertEqual(self.ledger.owner_withdrawal_pending_micro_units("alice"), 0)


if __name__ == "__main__":
    unittest.main()
