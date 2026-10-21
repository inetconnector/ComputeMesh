import unittest
import sqlite3

from services.orchestrator.architecture_hardening_part11 import (
    StrictLedgerManager,
    RevisionedJobManager,
    MonetaryUnitError,
    AppendOnlyLedgerError,
    OptimisticConcurrencyError
)

class TestArchitectureHardeningPart11(unittest.TestCase):

    def setUp(self):
        self.ledger_manager = StrictLedgerManager(":memory:")
        self.job_manager = RevisionedJobManager(":memory:")

    def test_ledger_forbids_float_amount(self):
        """Invariant: Monetary data uses integer fixed units, never floating-point."""
        with self.assertRaises(MonetaryUnitError) as context:
            self.ledger_manager.append_entry("entry-1", "user-acc", 10.5)
        self.assertIn("MUST NOT be a floating-point number", str(context.exception))

    def test_ledger_requires_int_amount(self):
        """Invariant: Monetary data uses integer fixed units, never floating-point."""
        with self.assertRaises(MonetaryUnitError):
            self.ledger_manager.append_entry("entry-1", "user-acc", "100")

    def test_ledger_append_only_forbids_update(self):
        """Invariant: Financial ledger entries are append-only."""
        self.ledger_manager.append_entry("entry-1", "user-acc", 100)

        with self.assertRaises(AppendOnlyLedgerError) as context:
            self.ledger_manager._attempt_illegal_update("entry-1", 200)
        self.assertIn("Updates are strictly forbidden", str(context.exception))

    def test_ledger_append_only_forbids_delete(self):
        """Invariant: Financial ledger entries are append-only."""
        self.ledger_manager.append_entry("entry-2", "user-acc", 100)

        with self.assertRaises(AppendOnlyLedgerError) as context:
            self.ledger_manager._attempt_illegal_delete("entry-2")
        self.assertIn("Deletions are strictly forbidden", str(context.exception))

    def test_ledger_append_only_forbids_duplicate_id(self):
        """Invariant: Financial ledger entries are append-only. Cannot overwrite."""
        self.ledger_manager.append_entry("entry-3", "user-acc", 100)
        with self.assertRaises(AppendOnlyLedgerError):
            self.ledger_manager.append_entry("entry-3", "user-acc", 150)

    def test_job_optimistic_concurrency_success(self):
        """Invariant: Job state transitions use optimistic concurrency or equivalent revision checks."""
        self.job_manager.create_job("job-1", "CREATED")

        job = self.job_manager.get_job("job-1")
        self.assertEqual(job["state"], "CREATED")
        self.assertEqual(job["revision"], 1)

        # Valid transition
        self.job_manager.transition_state("job-1", 1, "PLANNING")

        job = self.job_manager.get_job("job-1")
        self.assertEqual(job["state"], "PLANNING")
        self.assertEqual(job["revision"], 2)

    def test_job_optimistic_concurrency_failure(self):
        """Invariant: Job state transitions use optimistic concurrency or equivalent revision checks."""
        self.job_manager.create_job("job-2", "CREATED")

        # Transition with wrong expected revision
        with self.assertRaises(OptimisticConcurrencyError) as context:
            self.job_manager.transition_state("job-2", 2, "PLANNING")
        self.assertIn("expected revision 2", str(context.exception))

        # Original state remains
        job = self.job_manager.get_job("job-2")
        self.assertEqual(job["state"], "CREATED")
        self.assertEqual(job["revision"], 1)

if __name__ == '__main__':
    unittest.main()
