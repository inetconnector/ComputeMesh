from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from services.orchestrator.startup_recovery import RecoveryStateStore, reconcile_startup_state
from services.orchestrator.state_machine import JobState, ReservationState


class StartupRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RecoveryStateStore(":memory:")

    def tearDown(self) -> None:
        self.store.close()

    def _advance_job(self, job_id: str, target: JobState) -> None:
        order = [
            JobState.VALIDATING,
            JobState.PLANNING,
            JobState.RESERVING,
            JobState.PREPARING,
            JobState.RUNNING,
            JobState.VERIFYING,
            JobState.COMPLETED,
            JobState.SETTLED,
        ]
        record = self.store.ensure_job(job_id)
        for state in order:
            if state.value == target.value or record.state != target:
                result = self.store.transition_job(
                    job_id,
                    request_id=f"advance:{job_id}:{state.value}",
                    expected_revision=record.revision,
                    target=state,
                )
                record = self.store.get_job(job_id)
            if state == target:
                break

    def _bound_active_reservation(self, job_id: str, reservation_id: str) -> None:
        reservation = self.store.ensure_reservation(reservation_id)
        leased = self.store.lease_reservation(
            reservation_id,
            request_id=f"lease:{reservation_id}",
            expected_revision=reservation.revision,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        committed = self.store.commit_reservation(
            reservation_id,
            request_id=f"commit:{reservation_id}",
            expected_revision=leased.revision,
            job_id=job_id,
            stage_id="shared-inference",
        )
        self.store.transition_reservation(
            reservation_id,
            request_id=f"activate:{reservation_id}",
            expected_revision=committed.revision,
            target=ReservationState.ACTIVE,
        )

    def test_running_job_is_failed_and_bound_capacity_released(self) -> None:
        self._advance_job("job-running", JobState.RUNNING)
        self._bound_active_reservation("job-running", "res-running")

        report = reconcile_startup_state(self.store)

        self.assertEqual(self.store.get_job("job-running").state, JobState.FAILED)
        self.assertEqual(self.store.get_reservation("res-running").state, ReservationState.RELEASED)
        self.assertEqual(report.failed_jobs, ("job-running",))
        self.assertEqual(report.released_reservations, ("res-running",))

    def test_verifying_job_is_not_resumed_after_restart(self) -> None:
        self._advance_job("job-verifying", JobState.VERIFYING)
        self._bound_active_reservation("job-verifying", "res-verifying")

        reconcile_startup_state(self.store)

        self.assertEqual(self.store.get_job("job-verifying").state, JobState.FAILED)
        self.assertEqual(self.store.get_reservation("res-verifying").state, ReservationState.RELEASED)

    def test_completed_and_settled_jobs_are_untouched(self) -> None:
        self._advance_job("job-completed", JobState.COMPLETED)
        self._advance_job("job-settled", JobState.SETTLED)

        report = reconcile_startup_state(self.store)

        self.assertEqual(self.store.get_job("job-completed").state, JobState.COMPLETED)
        self.assertEqual(self.store.get_job("job-settled").state, JobState.SETTLED)
        self.assertEqual(report.failed_jobs, ())

    def test_expired_unbound_lease_expires_and_future_lease_survives(self) -> None:
        now = datetime.now(timezone.utc)
        expired = self.store.ensure_reservation("res-expired")
        leased = self.store.lease_reservation(
            "res-expired",
            request_id="lease-expired",
            expected_revision=expired.revision,
            expires_at=now + timedelta(seconds=1),
        )
        future = self.store.ensure_reservation("res-future")
        self.store.lease_reservation(
            "res-future",
            request_id="lease-future",
            expected_revision=future.revision,
            expires_at=now + timedelta(minutes=10),
        )

        report = reconcile_startup_state(self.store, now=now + timedelta(seconds=2))

        self.assertEqual(self.store.get_reservation("res-expired").state, ReservationState.EXPIRED)
        self.assertEqual(self.store.get_reservation("res-future").state, ReservationState.LEASED)
        self.assertEqual(report.expired_reservations, ("res-expired",))
        self.assertGreater(leased.revision, 0)

    def test_second_reconciliation_is_idempotent(self) -> None:
        self._advance_job("job-once", JobState.RUNNING)
        self._bound_active_reservation("job-once", "res-once")

        first = reconcile_startup_state(self.store)
        second = reconcile_startup_state(self.store)

        self.assertEqual(first.failed_jobs, ("job-once",))
        self.assertEqual(first.released_reservations, ("res-once",))
        self.assertEqual(second.failed_jobs, ())
        self.assertEqual(second.released_reservations, ())
        self.assertEqual(second.expired_reservations, ())


if __name__ == "__main__":
    unittest.main()
