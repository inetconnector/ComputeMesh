#!/usr/bin/env python3
import time
import unittest
from pathlib import Path
import tempfile
import shutil

from services.billing.ledger import Ledger, CreditHold, InsufficientBalanceError


class TestLedgerHoldsPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage_path = self.temp_dir / "journal.jsonl"
        self.ledger = Ledger(storage_path=self.storage_path)
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_test_persist",
            amount_micro_units=50_000_000,
            payment_reference="pay_ref_01",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_holds_persist_and_recover_on_restart(self) -> None:
        # Create an active hold
        hold1 = self.ledger.create_hold(
            account_id="cust_test_persist",
            amount_micro_units=10_000_000,
            model_id="qwen2.5",
            ttl_seconds=300.0,
        )
        self.assertEqual(self.ledger.get_available_balance("cust_test_persist"), 40_000_000)

        # Create a second hold that expires quickly
        hold2 = self.ledger.create_hold(
            account_id="cust_test_persist",
            amount_micro_units=5_000_000,
            model_id="qwen2.5",
            ttl_seconds=0.1,
        )
        self.assertEqual(self.ledger.get_available_balance("cust_test_persist"), 35_000_000)

        time.sleep(0.15)

        # Re-instantiate ledger from the same disk storage
        reloaded_ledger = Ledger(storage_path=self.storage_path)

        # hold1 should still be active and deducted
        self.assertTrue(reloaded_ledger._holds[hold1.hold_id].is_active)
        # hold2 should be recovered as expired
        self.assertEqual(reloaded_ledger._holds[hold2.hold_id].status, "expired")
        self.assertFalse(reloaded_ledger._holds[hold2.hold_id].is_active)

        # Available balance should be 50M - 10M = 40M
        self.assertEqual(reloaded_ledger.get_available_balance("cust_test_persist"), 40_000_000)

        # Capture hold1 on the reloaded ledger
        reloaded_ledger.capture_hold(
            hold_id=hold1.hold_id,
            job_id="job_persist_01",
            customer_account_id="cust_test_persist",
            provider_shares=[("node_01", 1.0)],
            model_id="qwen2.5",
            prompt_tokens=100,
            completion_tokens=200,
        )
        self.assertEqual(reloaded_ledger._holds[hold1.hold_id].status, "captured")

        # Restart again and verify hold1 is still captured
        reloaded_again = Ledger(storage_path=self.storage_path)
        self.assertEqual(reloaded_again._holds[hold1.hold_id].status, "captured")


if __name__ == "__main__":
    unittest.main()
