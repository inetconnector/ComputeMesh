from datetime import datetime, timedelta, timezone
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from services.orchestrator import ContractAdmission, ContractValidationError, ContractValidator, JobState, SQLiteStateStore


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.schemas = REPO / "protocol" / "schemas"
        self.validator = ContractValidator(self.schemas)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_job_admitted(self):
        job = {
            "schema_version": 1,
            "job_id": "job-1",
            "principal_id": "principal-1",
            "model_version": "model-v1",
            "state": "CREATED",
            "revision": 0,
            "policy": {"privacy_tier": "public_compute", "latency_class": "interactive"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with SQLiteStateStore(Path(self.tmp.name) / "state.db") as store:
            record = ContractAdmission(store, self.validator).admit_job(job)
            self.assertEqual(record.state, JobState.CREATED)

    def test_invalid_job_rejected_before_persistence(self):
        job = {
            "schema_version": 1,
            "job_id": "job-1",
            "principal_id": "principal-1",
            "model_version": "model-v1",
            "state": "CREATED",
            "revision": 0,
            "policy": {"privacy_tier": "secret_magic", "latency_class": "interactive"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = Path(self.tmp.name) / "state.db"
        with SQLiteStateStore(path) as store:
            with self.assertRaises(ContractValidationError):
                ContractAdmission(store, self.validator).admit_job(job)
            with self.assertRaises(KeyError):
                store.get_job("job-1")

    def test_non_initial_job_snapshot_not_admitted(self):
        job = {
            "schema_version": 1,
            "job_id": "job-1",
            "principal_id": "principal-1",
            "model_version": "model-v1",
            "state": "VALIDATING",
            "revision": 1,
            "policy": {"privacy_tier": "public_compute", "latency_class": "interactive"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with SQLiteStateStore(Path(self.tmp.name) / "state.db") as store:
            with self.assertRaisesRegex(ContractValidationError, "state=CREATED"):
                ContractAdmission(store, self.validator).admit_job(job)

    def test_valid_reservation_admitted(self):
        reservation = {
            "schema_version": 1,
            "reservation_id": "res-1",
            "node_id": "node-1",
            "state": "CANDIDATE",
            "revision": 0,
            "resource_request": {"device_ids": ["gpu-0"], "memory_bytes": 1024},
            "lease_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        }
        with SQLiteStateStore(Path(self.tmp.name) / "state.db") as store:
            record = ContractAdmission(store, self.validator).admit_reservation(reservation)
            self.assertEqual(record.state.value, "CANDIDATE")

    def test_unknown_field_rejected(self):
        job = {
            "schema_version": 1,
            "job_id": "job-1",
            "principal_id": "principal-1",
            "model_version": "model-v1",
            "state": "CREATED",
            "revision": 0,
            "policy": {"privacy_tier": "public_compute", "latency_class": "interactive"},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "arbitrary_command": "rm -rf /",
        }
        with self.assertRaises(ContractValidationError):
            self.validator.validate("job", job)


if __name__ == "__main__":
    unittest.main()
