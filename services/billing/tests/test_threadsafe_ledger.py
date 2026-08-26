from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from services.billing.ledger import DuplicateEventError, Ledger
from services.billing.threadsafe_ledger import SynchronizedLedgerProxy


class ThreadSafeLedgerTests(unittest.TestCase):
    def test_parallel_job_charges_remain_balanced_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            raw = Ledger(storage_path=path)
            ledger = SynchronizedLedgerProxy(raw)
            ledger.deposit_customer_credits(
                customer_account_id="acct",
                amount_micro_units=100_000_000,
                payment_reference="seed",
            )

            def charge(index: int):
                return ledger.record_job_execution(
                    job_id=f"job-{index}",
                    customer_account_id="acct",
                    provider_shares=[("node-a", 0.5), ("node-b", 0.5)],
                    model_id="qwen/qwen2.5-7b-instruct",
                    prompt_tokens=10,
                    completion_tokens=10,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                transactions = list(pool.map(charge, range(32)))

            self.assertEqual(len(transactions), 32)
            audit = ledger.reconcile()
            self.assertEqual(audit["status"], "balanced")
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(len(lines), 33)  # one deposit + 32 jobs

    def test_duplicate_job_is_atomically_rejected_under_race(self):
        raw = Ledger()
        ledger = SynchronizedLedgerProxy(raw)
        ledger.deposit_customer_credits(
            customer_account_id="acct",
            amount_micro_units=10_000_000,
            payment_reference="seed",
        )

        def same_charge(_index: int):
            try:
                ledger.record_job_execution(
                    job_id="same-job",
                    customer_account_id="acct",
                    provider_shares=[("node-a", 0.5), ("node-b", 0.5)],
                    model_id="qwen/qwen2.5-7b-instruct",
                    prompt_tokens=10,
                    completion_tokens=10,
                )
                return "recorded"
            except DuplicateEventError:
                return "duplicate"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(same_charge, range(2)))

        self.assertEqual(results.count("recorded"), 1)
        self.assertEqual(results.count("duplicate"), 1)
        self.assertEqual(ledger.reconcile()["total_transactions"], 2)


if __name__ == "__main__":
    unittest.main()
