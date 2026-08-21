from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

from services.orchestrator.handlers import handle_control_message
from services.orchestrator.persistence import SQLiteStateStore


def envelope(message_type, target_id, request_id, revision, payload, now):
    return {
        "protocol_major": 0,
        "protocol_minor": 2,
        "message_type": message_type,
        "request_id": request_id,
        "correlation_id": "corr-1",
        "actor_id": "svc:test",
        "target_id": target_id,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "expected_revision": revision,
        "payload": payload,
    }


class ControlHandlerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reservation_commit_persists_job_stage_binding(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            store.ensure_reservation("res-1")
            lease = (self.now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
            self.assertTrue(
                handle_control_message(
                    envelope(
                        "ReserveCapacity",
                        "res-1",
                        "lease-1",
                        0,
                        {"lease_expires_at": lease},
                        self.now,
                    ),
                    store,
                    now=self.now,
                ).ok
            )
            result = handle_control_message(
                envelope(
                    "CommitReservation",
                    "res-1",
                    "commit-1",
                    1,
                    {"job_id": "job-1", "stage_id": "stage-1"},
                    self.now,
                ),
                store,
                now=self.now,
            )
            self.assertTrue(result.ok)
            binding = store.get_reservation_binding("res-1")
            self.assertEqual(binding.job_id, "job-1")
            self.assertEqual(binding.stage_id, "stage-1")

    def test_same_request_and_payload_is_replay_safe(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            document = envelope(
                "CancelJob",
                "job-1",
                "request-1",
                0,
                {"reason": "user_request", "cutoff_policy": "stop_new_billable_work"},
                self.now,
            )
            first = handle_control_message(document, store, now=self.now)
            second = handle_control_message(document, store, now=self.now)
            self.assertTrue(first.changed)
            self.assertFalse(second.changed)
            self.assertEqual(second.revision, 1)

    def test_same_request_with_changed_payload_conflicts(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_reservation("res-1")
            lease_a = (self.now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
            lease_b = (self.now + timedelta(minutes=6)).isoformat().replace("+00:00", "Z")
            first = handle_control_message(
                envelope(
                    "ReserveCapacity",
                    "res-1",
                    "same-request",
                    0,
                    {"lease_expires_at": lease_a},
                    self.now,
                ),
                store,
                now=self.now,
            )
            second = handle_control_message(
                envelope(
                    "ReserveCapacity",
                    "res-1",
                    "same-request",
                    0,
                    {"lease_expires_at": lease_b},
                    self.now,
                ),
                store,
                now=self.now,
            )
            self.assertTrue(first.ok)
            self.assertFalse(second.ok)
            self.assertEqual(second.error.code, "IDEMPOTENCY_CONFLICT")

    def test_cancel_job_requires_protocol_payload(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            result = handle_control_message(
                envelope(
                    "CancelJob",
                    "job-1",
                    "cancel-1",
                    0,
                    {
                        "reason": "user_request",
                        "cutoff_policy": "stop_new_billable_work",
                    },
                    self.now,
                ),
                store,
                now=self.now,
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.state, "CANCELLED")

    def test_empty_cancel_payload_is_rejected(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            result = handle_control_message(
                envelope("CancelJob", "job-1", "cancel-1", 0, {}, self.now),
                store,
                now=self.now,
            )
            self.assertEqual(result.error.code, "INVALID_ARGUMENT")

    def test_missing_commit_job_rolls_back_reservation(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_reservation("res-1")
            lease = (self.now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
            handle_control_message(
                envelope(
                    "ReserveCapacity",
                    "res-1",
                    "lease-1",
                    0,
                    {"lease_expires_at": lease},
                    self.now,
                ),
                store,
                now=self.now,
            )
            result = handle_control_message(
                envelope(
                    "CommitReservation",
                    "res-1",
                    "commit-1",
                    1,
                    {"job_id": "missing", "stage_id": "stage-1"},
                    self.now,
                ),
                store,
                now=self.now,
            )
            self.assertEqual(result.error.code, "NOT_FOUND")
            record = store.get_reservation("res-1")
            self.assertEqual(record.state.value, "LEASED")
            self.assertEqual(record.revision, 1)

    def test_stale_revision_becomes_structured_retryable_error(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            store.ensure_reservation("res-1")
            lease = (self.now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
            handle_control_message(
                envelope(
                    "ReserveCapacity",
                    "res-1",
                    "lease-1",
                    0,
                    {"lease_expires_at": lease},
                    self.now,
                ),
                store,
                now=self.now,
            )
            result = handle_control_message(
                envelope(
                    "CommitReservation",
                    "res-1",
                    "commit-1",
                    0,
                    {"job_id": "job-1", "stage_id": "stage-1"},
                    self.now,
                ),
                store,
                now=self.now,
            )
            self.assertEqual(result.error.code, "STALE_REVISION")
            self.assertTrue(result.error.retryable)

    def test_expired_envelope_has_no_effect(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            old = self.now - timedelta(minutes=10)
            result = handle_control_message(
                envelope(
                    "CancelJob",
                    "job-1",
                    "cancel-old",
                    0,
                    {
                        "reason": "user_request",
                        "cutoff_policy": "stop_new_billable_work",
                    },
                    old,
                ),
                store,
                now=self.now,
            )
            self.assertEqual(result.error.code, "DEADLINE_EXCEEDED")
            self.assertEqual(store.get_job("job-1").revision, 0)

    def test_unknown_message_is_rejected(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            result = handle_control_message(
                envelope("DoAnything", "job-1", "x", 0, {}, self.now),
                store,
                now=self.now,
            )
            self.assertEqual(result.error.code, "UNSUPPORTED_MESSAGE")


if __name__ == "__main__":
    unittest.main()
