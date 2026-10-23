"""Unit tests for Architecture Hardening Part 19."""

import unittest
from services.orchestrator.architecture_hardening_part19 import (
    AmbiguousCompletionReconciler,
    DuplicateSegmentResultEnforcer,
    ConflictingDuplicateEnforcer,
    PlatformRetryBillingEnforcer,
    AmbiguousCompletionError,
    ConflictingDuplicateError
)

class TestAmbiguousCompletionReconciler(unittest.TestCase):
    def setUp(self) -> None:
        self.reconciler = AmbiguousCompletionReconciler()

    def test_settlement_allowed_default(self) -> None:
        # Should not raise
        self.reconciler.check_settlement_allowed("job_1")

    def test_settlement_prevented_when_ambiguous(self) -> None:
        self.reconciler.mark_ambiguous("job_2")
        with self.assertRaises(AmbiguousCompletionError):
            self.reconciler.check_settlement_allowed("job_2")

    def test_settlement_allowed_after_reconciliation(self) -> None:
        self.reconciler.mark_ambiguous("job_3")
        with self.assertRaises(AmbiguousCompletionError):
            self.reconciler.check_settlement_allowed("job_3")
        self.reconciler.mark_reconciled("job_3")
        self.reconciler.check_settlement_allowed("job_3")


class TestDuplicateSegmentResultEnforcer(unittest.TestCase):
    def setUp(self) -> None:
        self.enforcer = DuplicateSegmentResultEnforcer()

    def test_first_result_creates_metering(self) -> None:
        result = self.enforcer.record_metering("attempt_1", "result_A")
        self.assertTrue(result)

    def test_duplicate_result_creates_no_metering(self) -> None:
        self.enforcer.record_metering("attempt_1", "result_A")
        result = self.enforcer.record_metering("attempt_1", "result_A")
        self.assertFalse(result)

    def test_different_results_create_metering(self) -> None:
        self.enforcer.record_metering("attempt_1", "result_A")
        result = self.enforcer.record_metering("attempt_1", "result_B")
        self.assertTrue(result)


class TestConflictingDuplicateEnforcer(unittest.TestCase):
    def setUp(self) -> None:
        self.enforcer = ConflictingDuplicateEnforcer()

    def test_settlement_allowed_default(self) -> None:
        self.enforcer.check_settlement_allowed("job_1")

    def test_settlement_prevented_on_conflict(self) -> None:
        self.enforcer.mark_conflicting_duplicate("job_2")
        with self.assertRaises(ConflictingDuplicateError):
            self.enforcer.check_settlement_allowed("job_2")

    def test_settlement_allowed_after_investigation(self) -> None:
        self.enforcer.mark_conflicting_duplicate("job_3")
        with self.assertRaises(ConflictingDuplicateError):
            self.enforcer.check_settlement_allowed("job_3")
        self.enforcer.mark_investigated("job_3")
        self.enforcer.check_settlement_allowed("job_3")


class TestPlatformRetryBillingEnforcer(unittest.TestCase):
    def setUp(self) -> None:
        self.enforcer = PlatformRetryBillingEnforcer()

    def test_normal_billing(self) -> None:
        cost = self.enforcer.calculate_billable_cost(100, is_platform_retry=False, policy_assigns_cost=False)
        self.assertEqual(cost, 100)

    def test_platform_retry_no_cost(self) -> None:
        cost = self.enforcer.calculate_billable_cost(100, is_platform_retry=True, policy_assigns_cost=False)
        self.assertEqual(cost, 0)

    def test_platform_retry_with_policy_cost(self) -> None:
        cost = self.enforcer.calculate_billable_cost(100, is_platform_retry=True, policy_assigns_cost=True)
        self.assertEqual(cost, 100)


if __name__ == '__main__':
    unittest.main()
