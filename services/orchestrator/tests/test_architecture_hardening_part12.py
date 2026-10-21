"""Tests for ComputeMesh Architecture Hardening (Part 12)"""

import unittest
from services.orchestrator.architecture_hardening_part12 import (
    StaleProviderResponseEnforcer,
    UserCancellationPropagator,
    ExecutionEvidenceEnforcer,
    RecoveryStateEnforcer,
    StaleResponseError,
    CancellationPropagationError,
    MissingEvidenceError,
    InvalidRecoveryStateError
)

class TestArchitectureHardeningPart12(unittest.TestCase):
    def test_stale_provider_responses_cannot_overwrite_newer_placement(self) -> None:
        enforcer = StaleProviderResponseEnforcer()

        # Valid: Response is newer than current placement
        enforcer.enforce_newer_placement(current_revision=5, response_revision=6)

        # Invalid: Response is older
        with self.assertRaises(StaleResponseError) as ctx:
            enforcer.enforce_newer_placement(current_revision=5, response_revision=4)
        self.assertIn("cannot overwrite newer placement", str(ctx.exception))

        # Invalid: Response is the same
        with self.assertRaises(StaleResponseError) as ctx:
            enforcer.enforce_newer_placement(current_revision=5, response_revision=5)
        self.assertIn("cannot overwrite newer placement", str(ctx.exception))

    def test_user_cancellation_is_propagated(self) -> None:
        propagator = UserCancellationPropagator()

        # Valid: No active workers
        propagator.propagate_cancellation(job_id="job123", active_workers=[])

        # Valid: All workers notified successfully (default behavior of _notify_worker is True)
        propagator.propagate_cancellation(job_id="job123", active_workers=["worker1", "worker2"])

        # Invalid: Mock _notify_worker to return False
        class FailingPropagator(UserCancellationPropagator):
            def _notify_worker(self, worker: str, job_id: str) -> bool:
                if worker == "worker2":
                    return False
                return True

        failing_propagator = FailingPropagator()
        with self.assertRaises(CancellationPropagationError) as ctx:
            failing_propagator.propagate_cancellation(job_id="job123", active_workers=["worker1", "worker2"])
        self.assertIn("Failed to propagate user cancellation", str(ctx.exception))

    def test_billable_work_maps_to_accepted_execution_evidence(self) -> None:
        enforcer = ExecutionEvidenceEnforcer()

        # Valid: Accepted evidence
        enforcer.enforce_billable_work(job_id="job123", evidence={"accepted": True, "data": "..."})

        # Invalid: Missing evidence entirely
        with self.assertRaises(MissingEvidenceError) as ctx:
            enforcer.enforce_billable_work(job_id="job123", evidence=None)
        self.assertIn("lacks execution evidence", str(ctx.exception))

        # Invalid: Missing 'accepted' flag
        with self.assertRaises(MissingEvidenceError) as ctx:
            enforcer.enforce_billable_work(job_id="job123", evidence={"data": "..."})
        self.assertIn("requires accepted execution evidence", str(ctx.exception))

        # Invalid: 'accepted' flag is False
        with self.assertRaises(MissingEvidenceError) as ctx:
            enforcer.enforce_billable_work(job_id="job123", evidence={"accepted": False})
        self.assertIn("requires accepted execution evidence", str(ctx.exception))

    def test_recovery_never_assumes_failed_node_retained_state(self) -> None:
        enforcer = RecoveryStateEnforcer()

        # Valid: Node is not failed
        enforcer.validate_recovery(node_state={"failed": False, "retained_state": True})

        # Valid: Node is failed, but state is not retained
        enforcer.validate_recovery(node_state={"failed": True, "retained_state": False})

        # Valid: Default fields missing
        enforcer.validate_recovery(node_state={})

        # Invalid: Failed node assumes retained state
        with self.assertRaises(InvalidRecoveryStateError) as ctx:
            enforcer.validate_recovery(node_state={"failed": True, "retained_state": True})
        self.assertIn("cannot assume a failed node retained state", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
