from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from services.billing.confidential_escrow import (
    OWNER_CONFIDENTIAL_RESERVATION,
    ConfidentialEscrowOwnerCreditLedger,
    confidential_reservation_account,
)
from services.billing.ledger import BillingError, InsufficientBalanceError
from services.billing.owner_credits import (
    OWNER_EARNED,
    OWNER_PROMO,
    OWNER_PURCHASED,
    CreditDestination,
    owner_bucket_account,
)


class ConfidentialEscrowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.jsonl"
        self.ledger = ConfidentialEscrowOwnerCreditLedger(storage_path=self.path)
        self.owner = "owner-1"
        self.ledger.credit_owner_earned_credits(
            owner_id=self.owner,
            amount_micro_units=4_000_000,
            earning_reference="seed-earned",
        )
        self.ledger.deposit_owner_purchased_credits(
            owner_id=self.owner,
            amount_micro_units=3_000_000,
            payment_reference="seed-purchased",
        )
        self.ledger.grant_owner_promo_credits(
            owner_id=self.owner,
            amount_micro_units=2_000_000,
            grant_reference="seed-promo",
            policy_version="test",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _destination(self, amount: int) -> tuple[CreditDestination, ...]:
        return (
            CreditDestination(
                account_id="revenue:network_fee",
                account_type="revenue:network_fee",
                amount_micro_units=amount,
            ),
        )

    def test_reservation_is_a_persistent_journal_transfer(self) -> None:
        reservation = self.ledger.reserve_confidential_credits(
            owner_id=self.owner,
            reservation_id="job-1",
            amount_micro_units=5_000_000,
        )
        self.assertEqual(reservation.allocations, (("earned", 4_000_000), ("purchased", 1_000_000)))
        self.assertEqual(self.ledger.get_owner_balances(self.owner).total_spendable_micro_units, 4_000_000)
        self.assertEqual(
            self.ledger.get_balance(confidential_reservation_account(self.owner, "job-1", "earned")),
            4_000_000,
        )
        self.assertEqual(
            self.ledger.get_balance(confidential_reservation_account(self.owner, "job-1", "purchased")),
            1_000_000,
        )

        restarted = ConfidentialEscrowOwnerCreditLedger(storage_path=self.path)
        restored = restarted.get_confidential_reservation(
            owner_id=self.owner,
            reservation_id="job-1",
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.amount_micro_units, 5_000_000)
        self.assertEqual(restored.allocations, reservation.allocations)
        self.assertEqual(restored.state, "reserved")
        self.assertEqual(restarted.get_owner_balances(self.owner).total_spendable_micro_units, 4_000_000)

    def test_same_reservation_retry_is_idempotent(self) -> None:
        first = self.ledger.reserve_confidential_credits(
            owner_id=self.owner,
            reservation_id="job-retry",
            amount_micro_units=2_000_000,
        )
        second = self.ledger.reserve_confidential_credits(
            owner_id=self.owner,
            reservation_id="job-retry",
            amount_micro_units=2_000_000,
        )
        self.assertEqual(first.reserve_transaction.tx_id, second.reserve_transaction.tx_id)
        with self.assertRaisesRegex(BillingError, "amount mismatch"):
            self.ledger.reserve_confidential_credits(
                owner_id=self.owner,
                reservation_id="job-retry",
                amount_micro_units=2_000_001,
            )

    def test_concurrent_reservations_cannot_double_spend(self) -> None:
        # Only 9M is available in total; two 6M reservations cannot both win.
        def attempt(index: int) -> str:
            try:
                self.ledger.reserve_confidential_credits(
                    owner_id=self.owner,
                    reservation_id=f"race-{index}",
                    amount_micro_units=6_000_000,
                )
                return "won"
            except InsufficientBalanceError:
                return "insufficient"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(results.count("won"), 1)
        self.assertEqual(results.count("insufficient"), 1)

    def test_partial_settlement_refunds_original_source_buckets(self) -> None:
        self.ledger.reserve_confidential_credits(
            owner_id=self.owner,
            reservation_id="job-settle",
            amount_micro_units=6_000_000,
        )
        result = self.ledger.settle_confidential_reservation(
            owner_id=self.owner,
            reservation_id="job-settle",
            actual_amount_micro_units=4_500_000,
            destinations=self._destination(4_500_000),
        )
        self.assertEqual(result.charged_micro_units, 4_500_000)
        self.assertEqual(result.refunded_micro_units, 1_500_000)
        self.assertEqual(result.spent_earned_micro_units, 4_000_000)
        self.assertEqual(result.spent_purchased_micro_units, 500_000)
        self.assertEqual(result.spent_promo_micro_units, 0)
        self.assertEqual(self.ledger.get_balance(owner_bucket_account(self.owner, "earned")), 0)
        self.assertEqual(self.ledger.get_balance(owner_bucket_account(self.owner, "purchased")), 2_500_000)
        self.assertEqual(self.ledger.get_balance(owner_bucket_account(self.owner, "promo")), 2_000_000)
        for bucket in ("earned", "purchased", "promo"):
            self.assertEqual(
                self.ledger.get_balance(confidential_reservation_account(self.owner, "job-settle", bucket)),
                0,
            )
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

        restarted = ConfidentialEscrowOwnerCreditLedger(storage_path=self.path)
        restored = restarted.get_confidential_reservation(
            owner_id=self.owner,
            reservation_id="job-settle",
        )
        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.state, "settled")
        retry = restarted.settle_confidential_reservation(
            owner_id=self.owner,
            reservation_id="job-settle",
            actual_amount_micro_units=4_500_000,
            destinations=self._destination(4_500_000),
        )
        self.assertEqual(retry.transaction.tx_id, result.transaction.tx_id)
        self.assertEqual(restarted.reconcile()["status"], "balanced")

    def test_release_returns_all_reserved_provenance(self) -> None:
        initial = self.ledger.get_owner_balances(self.owner)
        self.ledger.reserve_confidential_credits(
            owner_id=self.owner,
            reservation_id="job-release",
            amount_micro_units=8_000_000,
        )
        release = self.ledger.release_confidential_reservation(
            owner_id=self.owner,
            reservation_id="job-release",
        )
        retry = self.ledger.release_confidential_reservation(
            owner_id=self.owner,
            reservation_id="job-release",
        )
        self.assertEqual(release.tx_id, retry.tx_id)
        after = self.ledger.get_owner_balances(self.owner)
        self.assertEqual(after.earned_micro_units, initial.earned_micro_units)
        self.assertEqual(after.purchased_micro_units, initial.purchased_micro_units)
        self.assertEqual(after.promo_micro_units, initial.promo_micro_units)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")
        with self.assertRaisesRegex(BillingError, "released"):
            self.ledger.settle_confidential_reservation(
                owner_id=self.owner,
                reservation_id="job-release",
                actual_amount_micro_units=1_000_000,
                destinations=self._destination(1_000_000),
            )

    def test_settled_reservation_cannot_be_released_or_overcharged(self) -> None:
        self.ledger.reserve_confidential_credits(
            owner_id=self.owner,
            reservation_id="job-final",
            amount_micro_units=1_000_000,
        )
        with self.assertRaisesRegex(BillingError, "pre-authorized"):
            self.ledger.settle_confidential_reservation(
                owner_id=self.owner,
                reservation_id="job-final",
                actual_amount_micro_units=1_000_001,
                destinations=self._destination(1_000_001),
            )
        self.ledger.settle_confidential_reservation(
            owner_id=self.owner,
            reservation_id="job-final",
            actual_amount_micro_units=1_000_000,
            destinations=self._destination(1_000_000),
        )
        with self.assertRaisesRegex(BillingError, "settled"):
            self.ledger.release_confidential_reservation(
                owner_id=self.owner,
                reservation_id="job-final",
            )

    def test_reservation_account_is_liability_and_has_no_content_fields(self) -> None:
        reservation = self.ledger.reserve_confidential_credits(
            owner_id=self.owner,
            reservation_id="job-no-content",
            amount_micro_units=500_000,
        )
        self.assertTrue(
            any(
                posting.account_type == OWNER_CONFIDENTIAL_RESERVATION
                for posting in reservation.reserve_transaction.postings
            )
        )
        encoded = repr(reservation.reserve_transaction.to_dict())
        self.assertNotIn("prompt", encoded.lower())
        self.assertNotIn("ciphertext", encoded.lower())


if __name__ == "__main__":
    unittest.main()
