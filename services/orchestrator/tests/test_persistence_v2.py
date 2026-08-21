from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.state_machine import IdempotencyConflict, ReservationState


class SQLiteStateStoreV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.db"
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_database_uses_schema_version_2(self):
        with SQLiteStateStore(self.path) as store:
            version = store._db.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
            self.assertEqual(version, "2")

    def test_version_1_database_migrates_in_place(self):
        db = sqlite3.connect(self.path)
        db.executescript(
            """
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1');
            CREATE TABLE entity_state (
                kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                state TEXT NOT NULL,
                revision INTEGER NOT NULL,
                lease_expires_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(kind, entity_id)
            );
            CREATE TABLE idempotency_effect (
                kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                target_state TEXT NOT NULL,
                result_state TEXT NOT NULL,
                result_revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(kind, entity_id, request_id)
            );
            """
        )
        db.close()

        with SQLiteStateStore(self.path) as store:
            version = store._db.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
            columns = {
                row["name"]
                for row in store._db.execute(
                    "PRAGMA table_info(idempotency_effect)"
                ).fetchall()
            }
            self.assertEqual(version, "2")
            self.assertIn("request_fingerprint", columns)
            store._db.execute("SELECT 1 FROM reservation_binding LIMIT 1")

    def test_commit_binding_survives_restart(self):
        expiry = self.now + timedelta(minutes=5)
        with SQLiteStateStore(self.path) as store:
            store.ensure_job("job-1")
            store.ensure_reservation("res-1")
            store.lease_reservation(
                "res-1", request_id="lease", expected_revision=0, expires_at=expiry
            )
            store.commit_reservation(
                "res-1",
                request_id="commit",
                expected_revision=1,
                job_id="job-1",
                stage_id="stage-1",
                request_fingerprint="fingerprint",
            )
        with SQLiteStateStore(self.path) as store:
            binding = store.get_reservation_binding("res-1")
            self.assertEqual(binding.job_id, "job-1")
            self.assertEqual(binding.stage_id, "stage-1")
            self.assertEqual(
                store.get_reservation("res-1").state,
                ReservationState.COMMITTED,
            )

    def test_changed_fingerprint_conflicts_before_revision_check(self):
        with SQLiteStateStore(self.path) as store:
            store.ensure_reservation("res-1")
            store.lease_reservation(
                "res-1",
                request_id="same",
                expected_revision=0,
                expires_at=self.now + timedelta(minutes=5),
                request_fingerprint="a",
            )
            with self.assertRaises(IdempotencyConflict):
                store.lease_reservation(
                    "res-1",
                    request_id="same",
                    expected_revision=0,
                    expires_at=self.now + timedelta(minutes=6),
                    request_fingerprint="b",
                )


if __name__ == "__main__":
    unittest.main()
