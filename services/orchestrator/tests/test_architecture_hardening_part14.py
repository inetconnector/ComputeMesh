"""Tests for ComputeMesh Architecture Hardening (Part 14)."""

import sqlite3
import unittest

from services.orchestrator.architecture_hardening_part14 import (
    AmbiguousCompletionEnforcer,
    SilentCorruptionEnforcer,
    BillingNeutralityEnforcer,
    AmbiguousCompletionError,
    SilentCorruptionError,
    BillingNeutralityError,
)

class TestArchitectureHardeningPart14(unittest.TestCase):
    def setUp(self) -> None:
        self.db = sqlite3.connect(":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def test_ambiguous_completion_reconciliation(self) -> None:
        enforcer = AmbiguousCompletionEnforcer(self.db)
        job_id = "job_ambig_1"

        # Record ambiguous completion
        enforcer.mark_completion(job_id, is_ambiguous=True)

        # Settlement should fail before reconciliation
        with self.assertRaisesRegex(AmbiguousCompletionError, "ambiguous completion that must be reconciled"):
            enforcer.enforce_settlement_prerequisites(job_id)

        # Reconcile completion
        enforcer.reconcile_completion(job_id)

        # Settlement should now pass
        enforcer.enforce_settlement_prerequisites(job_id)

    def test_unambiguous_completion_settlement(self) -> None:
        enforcer = AmbiguousCompletionEnforcer(self.db)
        job_id = "job_unambig_1"

        # Record unambiguous completion
        enforcer.mark_completion(job_id, is_ambiguous=False)

        # Settlement should pass
        enforcer.enforce_settlement_prerequisites(job_id)


    def test_missing_job_cannot_create_reconciliation_record(self) -> None:
        enforcer = AmbiguousCompletionEnforcer(self.db)
        with self.assertRaisesRegex(AmbiguousCompletionError, "no recorded completion"):
            enforcer.reconcile_completion("never-completed")
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM completion_status").fetchone()[0],
            0,
        )

    def test_re_marking_resets_reconciliation(self) -> None:
        enforcer = AmbiguousCompletionEnforcer(self.db)
        job_id = "job_remark_1"

        enforcer.mark_completion(job_id, is_ambiguous=True)
        enforcer.reconcile_completion(job_id)
        enforcer.enforce_settlement_prerequisites(job_id)  # Should pass

        # Remarking should reset is_reconciled to False
        enforcer.mark_completion(job_id, is_ambiguous=True)
        with self.assertRaisesRegex(AmbiguousCompletionError, "ambiguous completion that must be reconciled"):
            enforcer.enforce_settlement_prerequisites(job_id)

    def test_no_completion_settlement(self) -> None:
        enforcer = AmbiguousCompletionEnforcer(self.db)
        job_id = "job_unknown_1"

        # Settlement should fail when no completion info is known
        with self.assertRaisesRegex(AmbiguousCompletionError, "has no completion record"):
            enforcer.enforce_settlement_prerequisites(job_id)

    def test_silent_corruption(self) -> None:
        enforcer = SilentCorruptionEnforcer()

        # Success case
        enforcer.verify_integrity("abc", "abc", "component_x")

        # Failure case
        with self.assertRaisesRegex(SilentCorruptionError, "Integrity check failed"):
            enforcer.verify_integrity("abc", "def", "component_y")

    def test_billing_neutrality_enforcer(self) -> None:
        enforcer = BillingNeutralityEnforcer(self.db)
        job_id = "job_bill_1"

        # Success case: standard execution
        enforcer.record_execution_billing(
            job_id, execution_id="exec_1", is_platform_duplicate=False, policy_assigns_cost=False, amount_billed=100
        )

        # Success case: platform duplicate, no charge
        enforcer.record_execution_billing(
            job_id, execution_id="exec_2", is_platform_duplicate=True, policy_assigns_cost=False, amount_billed=0
        )

        # Success case: platform duplicate, policy assigns cost, so charge is allowed
        enforcer.record_execution_billing(
            job_id, execution_id="exec_3", is_platform_duplicate=True, policy_assigns_cost=True, amount_billed=50
        )

        # Failure case: platform duplicate, charge applied without policy allowing it
        with self.assertRaisesRegex(BillingNeutralityError, "billing-neutral unless policy explicitly assigns cost"):
            enforcer.record_execution_billing(
                job_id, execution_id="exec_4", is_platform_duplicate=True, policy_assigns_cost=False, amount_billed=100
            )

    def test_billing_neutrality_rejects_invalid_inputs_without_mutation(self) -> None:
        enforcer = BillingNeutralityEnforcer(self.db)
        rejected = (
            ("exec-negative", False, False, -1),
            ("exec-bool", False, False, True),
            ("exec-double", False, False, 1.25),
            ("exec-policy-string", True, "yes", 10),
            ("exec-duplicate-string", "false", False, 10),
        )
        for execution_id, is_duplicate, policy, amount in rejected:
            with self.subTest(execution_id=execution_id):
                with self.assertRaises(BillingNeutralityError):
                    enforcer.record_execution_billing(
                        "job-reject", execution_id, is_duplicate, policy, amount
                    )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM job_billing").fetchone()[0], 0
        )

    def test_execution_billing_is_idempotent_and_conflict_safe(self) -> None:
        enforcer = BillingNeutralityEnforcer(self.db)
        enforcer.record_execution_billing("job-a", "exec-a", False, False, 300)
        enforcer.record_execution_billing("job-a", "exec-a", False, False, 300)
        with self.assertRaisesRegex(BillingNeutralityError, "immutable"):
            enforcer.record_execution_billing("job-a", "exec-a", False, False, 500)
        self.assertEqual(
            self.db.execute(
                "SELECT amount_billed FROM job_billing "
                "WHERE job_id='job-a' AND execution_id='exec-a'"
            ).fetchone(), (300,)
        )

    def test_reloaded_enforcer_does_not_overwrite_billing_receipt(self) -> None:
        original = BillingNeutralityEnforcer(self.db)
        original.record_execution_billing(
            "job-restarted", "exec-original", False, False, 120
        )
        restarted = BillingNeutralityEnforcer(self.db)
        restarted.record_execution_billing(
            "job-restarted", "exec-original", False, False, 120
        )
        with self.assertRaisesRegex(BillingNeutralityError, "immutable"):
            restarted.record_execution_billing(
                "job-restarted", "exec-original", False, False, 240
            )
        self.assertEqual(
            self.db.execute(
                "SELECT amount_billed FROM job_billing "
                "WHERE job_id = ? AND execution_id = ?",
                ("job-restarted", "exec-original"),
            ).fetchone(),
            (120,),
        )


if __name__ == "__main__":
    unittest.main()
