"""Tests for unified owner earned/purchased/promo credit accounting."""
from pathlib import Path
import tempfile
import unittest

from services.billing.ledger import DuplicateEventError, InsufficientBalanceError
from services.billing.owner_credits import (
    CreditDestination,
    OwnerCreditLedger,
)


class TestOwnerCreditLedger(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger = OwnerCreditLedger(
            storage_path=Path(self.temp_dir.name) / "owner_ledger.jsonl"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _revenue_destination(self, amount: int) -> list[CreditDestination]:
        return [
            CreditDestination(
                account_id="revenue:network_fee",
                account_type="revenue:network_fee",
                amount_micro_units=amount,
            )
        ]

    def test_three_balance_classes_and_withdrawable_invariant(self) -> None:
        self.ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=10_000_000,
            earning_reference="job-1",
        )
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=20_000_000,
            payment_reference="stripe-1",
        )
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=25_000_000,
            grant_reference="alice-device-v1",
            policy_version="onboarding-v1",
        )

        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.earned_micro_units, 10_000_000)
        self.assertEqual(balances.purchased_micro_units, 20_000_000)
        self.assertEqual(balances.promo_micro_units, 25_000_000)
        self.assertEqual(balances.total_spendable_micro_units, 55_000_000)
        self.assertEqual(balances.withdrawable_micro_units, 10_000_000)

    def test_spend_order_is_earned_then_purchased_then_promo(self) -> None:
        self.ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=10_000_000,
            earning_reference="job-1",
        )
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=20_000_000,
            payment_reference="stripe-1",
        )
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=25_000_000,
            grant_reference="alice-device-v1",
            policy_version="onboarding-v1",
        )

        result = self.ledger.spend_owner_credits(
            owner_id="alice",
            amount_micro_units=35_000_000,
            destinations=self._revenue_destination(35_000_000),
            spend_reference="api-job-1",
        )
        self.assertEqual(result.spent_earned_micro_units, 10_000_000)
        self.assertEqual(result.spent_purchased_micro_units, 20_000_000)
        self.assertEqual(result.spent_promo_micro_units, 5_000_000)

        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.earned_micro_units, 0)
        self.assertEqual(balances.purchased_micro_units, 0)
        self.assertEqual(balances.promo_micro_units, 20_000_000)
        self.assertEqual(balances.withdrawable_micro_units, 0)

    def test_earned_balance_can_be_spent_exactly_to_zero(self) -> None:
        self.ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=7_500_000,
            earning_reference="provider-job",
        )
        self.ledger.spend_owner_credits(
            owner_id="alice",
            amount_micro_units=7_500_000,
            destinations=self._revenue_destination(7_500_000),
            spend_reference="consume-all",
        )
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.total_spendable_micro_units, 0)
        with self.assertRaises(InsufficientBalanceError):
            self.ledger.spend_owner_credits(
                owner_id="alice",
                amount_micro_units=1,
                destinations=self._revenue_destination(1),
                spend_reference="one-too-many",
            )

    def test_hold_reduces_withdrawable_and_spendable_until_capture(self) -> None:
        self.ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=10_000_000,
            earning_reference="provider-job",
        )
        hold = self.ledger.create_owner_hold(
            owner_id="alice",
            amount_micro_units=8_000_000,
            purpose="inference",
            hold_id="hold-1",
        )
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.withdrawable_micro_units, 2_000_000)
        self.assertEqual(balances.available_spendable_micro_units, 2_000_000)

        result = self.ledger.capture_owner_hold(
            hold_id=hold.hold_id,
            actual_amount_micro_units=6_000_000,
            destinations=self._revenue_destination(6_000_000),
            spend_reference="held-api-job",
        )
        self.assertEqual(result.spent_earned_micro_units, 6_000_000)
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.earned_micro_units, 4_000_000)
        self.assertEqual(balances.withdrawable_micro_units, 4_000_000)

    def test_release_hold_restores_availability(self) -> None:
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=25_000_000,
            grant_reference="device",
            policy_version="onboarding-v1",
        )
        hold = self.ledger.create_owner_hold(
            owner_id="alice",
            amount_micro_units=20_000_000,
            hold_id="promo-hold",
        )
        self.assertEqual(
            self.ledger.get_owner_balances("alice").available_spendable_micro_units,
            5_000_000,
        )
        self.assertTrue(self.ledger.release_owner_hold(hold.hold_id))
        self.assertEqual(
            self.ledger.get_owner_balances("alice").available_spendable_micro_units,
            25_000_000,
        )

    def test_duplicate_promo_grant_reference_is_rejected(self) -> None:
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=25_000_000,
            grant_reference="device-v1",
            policy_version="onboarding-v1",
        )
        with self.assertRaises(DuplicateEventError):
            self.ledger.grant_owner_promo_credits(
                owner_id="alice",
                amount_micro_units=25_000_000,
                grant_reference="device-v1",
                policy_version="onboarding-v1",
            )

    def test_disk_reload_preserves_bucket_balances_and_reconciles(self) -> None:
        path = Path(self.temp_dir.name) / "persistent_owner_ledger.jsonl"
        ledger = OwnerCreditLedger(storage_path=path)
        ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=8_000_000,
            earning_reference="job-persist",
        )
        ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=25_000_000,
            grant_reference="promo-persist",
            policy_version="onboarding-v1",
        )
        reloaded = OwnerCreditLedger(storage_path=path)
        balances = reloaded.get_owner_balances("alice")
        self.assertEqual(balances.earned_micro_units, 8_000_000)
        self.assertEqual(balances.promo_micro_units, 25_000_000)
        self.assertEqual(reloaded.reconcile()["status"], "balanced")


if __name__ == "__main__":
    unittest.main()
