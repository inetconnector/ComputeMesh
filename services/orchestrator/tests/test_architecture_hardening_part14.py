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

    def test_no_completion_settlement(self) -> None:
        enforcer = AmbiguousCompletionEnforcer(self.db)
        job_id = "job_unknown_1"

        # Settlement should pass (or not raise) when no completion info is known
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

if __name__ == "__main__":
    unittest.main()
