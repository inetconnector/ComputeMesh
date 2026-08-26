from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.identity.store import SQLiteIdentityStore
from services.identity.threaded_resolver import SQLiteIdentityKeyResolver
from services.orchestrator.startup_recovery import RecoveryStateStore
from services.orchestrator.state_machine import JobState, ReservationState


class ThreadedLiveSQLiteTests(unittest.TestCase):
    def test_one_live_state_store_handles_parallel_request_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecoveryStateStore(Path(tmp) / "state.sqlite3")
            try:
                def run(index: int) -> tuple[JobState, ReservationState]:
                    job_id = f"job-{index}"
                    reservation_id = f"res-{index}"
                    store.ensure_job(job_id)
                    for target in (
                        JobState.VALIDATING,
                        JobState.PLANNING,
                        JobState.RESERVING,
                    ):
                        current = store.get_job(job_id)
                        store.transition_job(
                            job_id,
                            request_id=f"{job_id}:{target.value}",
                            expected_revision=current.revision,
                            target=target,
                        )
                    reservation = store.ensure_reservation(reservation_id)
                    leased = store.lease_reservation(
                        reservation_id,
                        request_id=f"{reservation_id}:lease",
                        expected_revision=reservation.revision,
                        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                    )
                    committed = store.commit_reservation(
                        reservation_id,
                        request_id=f"{reservation_id}:commit",
                        expected_revision=leased.revision,
                        job_id=job_id,
                        stage_id="shared-inference",
                    )
                    store.transition_reservation(
                        reservation_id,
                        request_id=f"{reservation_id}:active",
                        expected_revision=committed.revision,
                        target=ReservationState.ACTIVE,
                    )
                    return store.get_job(job_id).state, store.get_reservation(reservation_id).state

                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(run, range(32)))

                self.assertEqual(len(results), 32)
                self.assertTrue(all(job == JobState.RESERVING for job, _ in results))
                self.assertTrue(all(res == ReservationState.ACTIVE for _, res in results))
            finally:
                store.close()

    def test_identity_keys_can_be_resolved_from_different_worker_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.sqlite3"
            private_key = Ed25519PrivateKey.generate()
            public_key = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            with SQLiteIdentityStore(path) as store:
                token = store.create_enrollment_token(
                    "principal-a",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
                enrolled = store.enroll(token, public_key)

            resolver = SQLiteIdentityKeyResolver(path)

            def resolve(_index: int):
                return resolver.resolve_key(enrolled.node_id, enrolled.key_id)

            with ThreadPoolExecutor(max_workers=8) as pool:
                keys = list(pool.map(resolve, range(32)))

            self.assertEqual(len(keys), 32)
            self.assertTrue(all(item.node_id == enrolled.node_id for item in keys))
            self.assertTrue(all(item.public_key == public_key for item in keys))


if __name__ == "__main__":
    unittest.main()
