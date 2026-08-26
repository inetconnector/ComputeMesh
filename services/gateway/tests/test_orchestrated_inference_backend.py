from __future__ import annotations

import tempfile
import unittest

from services.gateway.inference_backend import (
    BackendResult,
    InferenceBackendError,
    OrchestratedInferenceBackend,
)
from services.gateway.placement_selection import PlacementSelection
from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.state_machine import JobState, ReservationState


class _SuccessBackend:
    def complete(self, *, model_id, messages):
        return BackendResult("real runtime output", 11, 7)


class _FailBackend:
    def complete(self, *, model_id, messages):
        raise InferenceBackendError("runtime unavailable")


class OrchestratedInferenceBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = f"{self.tmp.name}/orchestrator.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _placement() -> PlacementSelection:
        return PlacementSelection(
            decision_id="placement-0123456789abcdef",
            model_id="test-model",
            artifact_digest="sha256:" + "a" * 64,
            provider_node_ids=("node-a", "node-b"),
            layer_ranges=(("node-a", 0, 16), ("node-b", 16, 32)),
        )

    def test_success_requires_and_releases_two_capacity_reservations(self):
        store = SQLiteStateStore(self.db_path)
        backend = OrchestratedInferenceBackend(
            delegate=_SuccessBackend(),
            store=store,
            provider_node_ids=["node-a", "node-b"],
            id_factory=lambda: "job-success",
        )

        result = backend.complete(
            model_id="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        self.assertEqual(result.text, "real runtime output")
        self.assertEqual(result.prompt_tokens, 11)
        self.assertEqual(result.completion_tokens, 7)
        self.assertEqual(result.execution_job_id, "job-success")
        self.assertIsNone(result.provider_shares)
        job = store.get_job("job-success")
        self.assertEqual(job.state, JobState.COMPLETED)
        self.assertEqual(job.revision, 7)

        reservations = backend._reservation_ids("job-success")
        self.assertEqual(len(reservations), 2)
        for reservation_id in reservations:
            reservation = store.get_reservation(reservation_id)
            self.assertEqual(reservation.state, ReservationState.RELEASED)
            binding = store.get_reservation_binding(reservation_id)
            self.assertEqual(binding.job_id, "job-success")
            self.assertTrue(binding.stage_id.startswith("inference:node-"))
        store.close()

    def test_runtime_failure_marks_job_failed_and_releases_capacity(self):
        store = SQLiteStateStore(self.db_path)
        backend = OrchestratedInferenceBackend(
            delegate=_FailBackend(),
            store=store,
            provider_node_ids=["node-a", "node-b"],
            id_factory=lambda: "job-fail",
        )

        with self.assertRaisesRegex(InferenceBackendError, "runtime unavailable"):
            backend.complete(
                model_id="test-model",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertEqual(store.get_job("job-fail").state, JobState.FAILED)
        for reservation_id in backend._reservation_ids("job-fail"):
            self.assertEqual(
                store.get_reservation(reservation_id).state,
                ReservationState.RELEASED,
            )
        store.close()

    def test_requires_at_least_two_unique_provider_nodes(self):
        store = SQLiteStateStore(self.db_path)
        with self.assertRaisesRegex(ValueError, "at least two"):
            OrchestratedInferenceBackend(
                delegate=_SuccessBackend(),
                store=store,
                provider_node_ids=["node-a"],
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            OrchestratedInferenceBackend(
                delegate=_SuccessBackend(),
                store=store,
                provider_node_ids=["node-a", "node-a"],
            )
        store.close()

    def test_scheduler_placement_requires_shared_run_evidence(self):
        store = SQLiteStateStore(self.db_path)
        placement = self._placement()
        with self.assertRaisesRegex(ValueError, "requires shared-run evidence"):
            OrchestratedInferenceBackend(
                delegate=_SuccessBackend(),
                store=store,
                provider_node_ids=placement.provider_node_ids,
                placement=placement,
            )
        store.close()

    def test_scheduler_placement_requires_execution_attestations(self):
        store = SQLiteStateStore(self.db_path)
        placement = self._placement()
        with self.assertRaisesRegex(ValueError, "requires execution attestations"):
            OrchestratedInferenceBackend(
                delegate=_SuccessBackend(),
                store=store,
                provider_node_ids=placement.provider_node_ids,
                placement=placement,
                execution_evidence_path="evidence.json",
            )
        store.close()

    def test_scheduler_placement_requires_identity_resolver(self):
        store = SQLiteStateStore(self.db_path)
        placement = self._placement()
        with self.assertRaisesRegex(ValueError, "requires an identity resolver"):
            OrchestratedInferenceBackend(
                delegate=_SuccessBackend(),
                store=store,
                provider_node_ids=placement.provider_node_ids,
                placement=placement,
                execution_evidence_path="evidence.json",
                execution_attestation_path="attestations.json",
            )
        store.close()


if __name__ == "__main__":
    unittest.main()
