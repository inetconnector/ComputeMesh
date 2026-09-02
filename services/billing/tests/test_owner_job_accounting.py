"""Tests for owner-aware marketplace/self-compute settlement math."""
from pathlib import Path
import tempfile
import unittest

from services.billing.owner_credits import OwnerCreditLedger
from services.billing.owner_job_accounting import (
    ProviderOwnerShare,
    capture_owner_job_hold,
    quote_owner_job,
)


class TestOwnerJobAccounting(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger = OwnerCreditLedger(
            storage_path=Path(self.temp_dir.name) / "ledger.jsonl"
        )
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=100_000_000,
            payment_reference="fund-alice",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pure_marketplace_uses_full_charge_and_25_percent_operator_fee(self) -> None:
        quote = quote_owner_job(
            customer_owner_id="alice",
            gross_reference_micro_units=10_000_000,
            provider_shares=[ProviderOwnerShare("rig-bob", "bob", 1.0)],
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,
        )
        self.assertTrue(quote.is_pure_marketplace)
        self.assertEqual(quote.customer_charge_micro_units, 10_000_000)
        self.assertEqual(quote.operator_fee_micro_units, 2_500_000)
        self.assertEqual(quote.provider_earned_by_owner, (("bob", 7_500_000),))

        hold = self.ledger.create_owner_hold(
            owner_id="alice",
            amount_micro_units=10_000_000,
            hold_id="market-hold",
        )
        capture_owner_job_hold(self.ledger, hold=hold, quote=quote, job_id="job-market")
        self.assertEqual(
            self.ledger.get_owner_balances("alice").purchased_micro_units,
            90_000_000,
        )
        self.assertEqual(
            self.ledger.get_owner_balances("bob").earned_micro_units,
            7_500_000,
        )
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 2_500_000)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_pure_self_compute_charges_only_10_percent_infrastructure_fee(self) -> None:
        quote = quote_owner_job(
            customer_owner_id="alice",
            gross_reference_micro_units=10_000_000,
            provider_shares=[ProviderOwnerShare("rig-alice", "alice", 1.0)],
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,
        )
        self.assertTrue(quote.is_pure_self_compute)
        self.assertEqual(quote.customer_charge_micro_units, 1_000_000)
        self.assertEqual(quote.operator_fee_micro_units, 1_000_000)
        self.assertEqual(quote.provider_earned_by_owner, ())

        hold = self.ledger.create_owner_hold(
            owner_id="alice",
            amount_micro_units=10_000_000,
            hold_id="self-hold",
        )
        capture_owner_job_hold(self.ledger, hold=hold, quote=quote, job_id="job-self")
        self.assertEqual(
            self.ledger.get_owner_balances("alice").purchased_micro_units,
            99_000_000,
        )
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 1_000_000)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_mixed_job_applies_self_and_foreign_policy_proportionally(self) -> None:
        quote = quote_owner_job(
            customer_owner_id="alice",
            gross_reference_micro_units=10_000_000,
            provider_shares=[
                ProviderOwnerShare("rig-alice", "alice", 0.7),
                ProviderOwnerShare("rig-bob", "bob", 0.3),
            ],
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,
        )
        # 7.00 gross self share -> 0.70 infra fee.
        # 3.00 gross foreign share -> 3.00 customer debit, 0.75 operator, 2.25 Bob.
        self.assertEqual(quote.self_compute_gross_micro_units, 7_000_000)
        self.assertEqual(quote.foreign_compute_gross_micro_units, 3_000_000)
        self.assertEqual(quote.customer_charge_micro_units, 3_700_000)
        self.assertEqual(quote.operator_fee_micro_units, 1_450_000)
        self.assertEqual(quote.provider_earned_by_owner, (("bob", 2_250_000),))

        hold = self.ledger.create_owner_hold(
            owner_id="alice",
            amount_micro_units=10_000_000,
            hold_id="mixed-hold",
        )
        capture_owner_job_hold(self.ledger, hold=hold, quote=quote, job_id="job-mixed")
        self.assertEqual(
            self.ledger.get_owner_balances("alice").purchased_micro_units,
            96_300_000,
        )
        self.assertEqual(
            self.ledger.get_owner_balances("bob").earned_micro_units,
            2_250_000,
        )
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 1_450_000)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_multiple_nodes_owned_by_same_foreign_owner_aggregate_earned_credit(self) -> None:
        quote = quote_owner_job(
            customer_owner_id="alice",
            gross_reference_micro_units=12_000_000,
            provider_shares=[
                ProviderOwnerShare("bob-rig-1", "bob", 1.0),
                ProviderOwnerShare("bob-rig-2", "bob", 1.0),
            ],
            marketplace_fee_bps=2500,
        )
        self.assertEqual(quote.provider_earned_by_owner, (("bob", 9_000_000),))
        self.assertEqual(len(quote.provider_shares), 2)
        self.assertEqual(sum(item.gross_micro_units for item in quote.provider_shares), 12_000_000)

    def test_tiny_nonzero_fee_does_not_round_away(self) -> None:
        quote = quote_owner_job(
            customer_owner_id="alice",
            gross_reference_micro_units=1,
            provider_shares=[ProviderOwnerShare("alice-rig", "alice", 1.0)],
            self_compute_fee_bps=1,
        )
        self.assertEqual(quote.customer_charge_micro_units, 1)
        self.assertEqual(quote.operator_fee_micro_units, 1)

    def test_zero_self_fee_can_release_hold_without_fake_money(self) -> None:
        quote = quote_owner_job(
            customer_owner_id="alice",
            gross_reference_micro_units=1_000_000,
            provider_shares=[ProviderOwnerShare("alice-rig", "alice", 1.0)],
            self_compute_fee_bps=0,
        )
        hold = self.ledger.create_owner_hold(
            owner_id="alice",
            amount_micro_units=1_000_000,
            hold_id="free-self-research",
        )
        result = capture_owner_job_hold(
            self.ledger,
            hold=hold,
            quote=quote,
            job_id="job-zero-self-fee",
        )
        self.assertIsNone(result)
        self.assertEqual(
            self.ledger.get_owner_balances("alice").available_spendable_micro_units,
            100_000_000,
        )


if __name__ == "__main__":
    unittest.main()
