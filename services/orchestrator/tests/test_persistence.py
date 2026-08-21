from datetime import datetime, timedelta, timezone
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ("state_machine", "persistence"):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)

sm = sys.modules["state_machine"]
p = sys.modules["persistence"]


class SQLiteStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_job_state_survives_reopen(self):
        with p.SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            store.transition_job("job-1", request_id="validate", expected_revision=0, target=sm.JobState.VALIDATING)
        with p.SQLiteStateStore(self.path) as store:
            record = store.get_job("job-1")
            self.assertEqual(record.state, sm.JobState.VALIDATING)
            self.assertEqual(record.revision, 1)

    def test_idempotency_survives_restart(self):
        with p.SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            first = store.transition_job("job-1", request_id="validate", expected_revision=0, target=sm.JobState.VALIDATING)
            self.assertTrue(first.changed)
        with p.SQLiteStateStore(self.path) as store:
            replay = store.transition_job("job-1", request_id="validate", expected_revision=0, target=sm.JobState.VALIDATING)
            self.assertFalse(replay.changed)
            self.assertEqual(replay.revision, 1)

    def test_conflicting_idempotency_key_rolls_back(self):
        with p.SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            store.transition_job("job-1", request_id="same", expected_revision=0, target=sm.JobState.VALIDATING)
            with self.assertRaises(sm.IdempotencyConflict):
                store.transition_job("job-1", request_id="same", expected_revision=1, target=sm.JobState.PLANNING)
            self.assertEqual(store.get_job("job-1").revision, 1)

    def test_stale_writer_rejected_across_connections(self):
        a = p.SQLiteStateStore(self.path)
        b = p.SQLiteStateStore(self.path)
        try:
            a.ensure_job("job-1")
            self.assertEqual(a.get_job("job-1").revision, 0)
            self.assertEqual(b.get_job("job-1").revision, 0)
            a.transition_job("job-1", request_id="a", expected_revision=0, target=sm.JobState.VALIDATING)
            with self.assertRaises(sm.StaleRevision):
                b.transition_job("job-1", request_id="b", expected_revision=0, target=sm.JobState.VALIDATING)
        finally:
            a.close()
            b.close()

    def test_reservation_lease_persists_and_expires(self):
        expiry = datetime.now(timezone.utc) + timedelta(seconds=1)
        with p.SQLiteStateStore(self.path) as store:
            store.ensure_reservation("res-1")
            store.lease_reservation("res-1", request_id="lease", expected_revision=0, expires_at=expiry)
        with p.SQLiteStateStore(self.path) as store:
            record = store.get_reservation("res-1")
            self.assertEqual(record.state, sm.ReservationState.LEASED)
            self.assertIsNotNone(record.lease_expires_at)
            result = store.expire_reservation_if_due(
                "res-1", request_id="expire", expected_revision=1, now=expiry + timedelta(milliseconds=1)
            )
            self.assertIsNotNone(result)
            self.assertEqual(store.get_reservation("res-1").state, sm.ReservationState.EXPIRED)
            self.assertIsNone(store.get_reservation("res-1").lease_expires_at)

    def test_commit_wins_before_expiry_then_expire_is_noop(self):
        expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        with p.SQLiteStateStore(self.path) as store:
            store.ensure_reservation("res-1")
            store.lease_reservation("res-1", request_id="lease", expected_revision=0, expires_at=expiry)
            store.transition_reservation("res-1", request_id="commit", expected_revision=1, target=sm.ReservationState.COMMITTED)
            result = store.expire_reservation_if_due(
                "res-1", request_id="expire", expected_revision=2, now=expiry + timedelta(seconds=1)
            )
            self.assertIsNone(result)
            self.assertEqual(store.get_reservation("res-1").state, sm.ReservationState.COMMITTED)

    def test_invalid_transition_does_not_advance_revision(self):
        with p.SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            with self.assertRaises(sm.InvalidTransition):
                store.transition_job("job-1", request_id="skip", expected_revision=0, target=sm.JobState.RUNNING)
            self.assertEqual(store.get_job("job-1").revision, 0)

    def test_ensure_is_idempotent(self):
        with p.SQLiteStateStore(self.path) as store:
            first = store.ensure_job("job-1")
            second = store.ensure_job("job-1")
            self.assertEqual(first, second)
            self.assertEqual(first.revision, 0)


if __name__ == "__main__":
    unittest.main()
