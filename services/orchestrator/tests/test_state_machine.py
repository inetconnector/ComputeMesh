from datetime import datetime, timedelta, timezone
import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "state_machine.py"
spec = importlib.util.spec_from_file_location("cm_state_machine", MODULE_PATH)
sm = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = sm
spec.loader.exec_module(sm)


class ReservationStateMachineTests(unittest.TestCase):
    def test_happy_path(self):
        machine = sm.ReservationStateMachine()
        expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.assertEqual(machine.lease(request_id="r1", expected_revision=0, expires_at=expiry).revision, 1)
        machine.transition(request_id="r2", expected_revision=1, target=sm.ReservationState.COMMITTED)
        machine.transition(request_id="r3", expected_revision=2, target=sm.ReservationState.ACTIVE)
        result = machine.transition(request_id="r4", expected_revision=3, target=sm.ReservationState.RELEASED)
        self.assertEqual(result.state, sm.ReservationState.RELEASED)
        self.assertEqual(machine.revision, 4)
        self.assertIsNone(machine.lease_expires_at)

    def test_duplicate_request_is_idempotent(self):
        machine = sm.ReservationStateMachine()
        expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        first = machine.lease(request_id="same", expected_revision=0, expires_at=expiry)
        second = machine.lease(request_id="same", expected_revision=0, expires_at=expiry)
        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(machine.revision, 1)

    def test_conflicting_idempotency_key_rejected(self):
        machine = sm.ReservationStateMachine()
        expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        machine.lease(request_id="same", expected_revision=0, expires_at=expiry)
        with self.assertRaises(sm.IdempotencyConflict):
            machine.transition(request_id="same", expected_revision=1, target=sm.ReservationState.RELEASED)

    def test_expiry_and_commit_race_has_one_winner(self):
        machine = sm.ReservationStateMachine()
        expiry = datetime.now(timezone.utc) + timedelta(milliseconds=1)
        machine.lease(request_id="lease", expected_revision=0, expires_at=expiry)
        machine.expire_if_due(
            request_id="expire",
            expected_revision=1,
            now=expiry + timedelta(milliseconds=1),
        )
        with self.assertRaises(sm.StaleRevision):
            machine.transition(request_id="commit", expected_revision=1, target=sm.ReservationState.COMMITTED)


class JobStateMachineTests(unittest.TestCase):
    def test_happy_path(self):
        machine = sm.JobStateMachine()
        states = [
            sm.JobState.VALIDATING,
            sm.JobState.PLANNING,
            sm.JobState.RESERVING,
            sm.JobState.PREPARING,
            sm.JobState.RUNNING,
            sm.JobState.VERIFYING,
            sm.JobState.COMPLETED,
            sm.JobState.SETTLED,
        ]
        for index, state in enumerate(states):
            machine.transition(request_id=f"j{index}", expected_revision=index, target=state)
        self.assertEqual(machine.state, sm.JobState.SETTLED)
        self.assertEqual(machine.revision, len(states))

    def test_cancel_is_idempotent(self):
        machine = sm.JobStateMachine()
        first = machine.transition(request_id="cancel", expected_revision=0, target=sm.JobState.CANCELLED)
        second = machine.transition(request_id="cancel", expected_revision=0, target=sm.JobState.CANCELLED)
        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(machine.revision, 1)

    def test_stale_revision_rejected(self):
        machine = sm.JobStateMachine()
        machine.transition(request_id="validate", expected_revision=0, target=sm.JobState.VALIDATING)
        with self.assertRaises(sm.StaleRevision):
            machine.transition(request_id="plan", expected_revision=0, target=sm.JobState.PLANNING)

    def test_invalid_transition_rejected(self):
        machine = sm.JobStateMachine()
        with self.assertRaises(sm.InvalidTransition):
            machine.transition(request_id="skip", expected_revision=0, target=sm.JobState.RUNNING)


if __name__ == "__main__":
    unittest.main()
