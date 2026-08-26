from __future__ import annotations

from pathlib import Path

from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.shared_request_live import SharedRequestCancelled
from services.orchestrator.shared_request_backend import SharedRequestOrchestratedBackend
from services.orchestrator.state_machine import JobState, ReservationState
from services.orchestrator.tests.test_shared_request_backend import (
    SharedRequestBackendTests,
    _SigningTransport,
)


class _CountingTransport(_SigningTransport):
    def __init__(self, keys):
        super().__init__(keys)
        self.calls = 0

    def request_execution_attestation(self, *, node_id, request_document, timeout_seconds):
        self.calls += 1
        return super().request_execution_attestation(
            node_id=node_id,
            request_document=request_document,
            timeout_seconds=timeout_seconds,
        )


class SharedRequestCancellationTests(SharedRequestBackendTests):
    def test_cancelled_runtime_marks_job_cancelled_and_skips_attestation(self):
        transport = _CountingTransport(self.keys)

        def cancelled_runner(**kwargs):
            raise SharedRequestCancelled("cancelled by request owner")

        backend = SharedRequestOrchestratedBackend(
            store=self.store,
            placement=self.placement,
            bundle_path=self.root / "unused-bundle.json",
            llama_server=self.root / "unused-llama-server",
            model_path=self.root / "unused-model.gguf",
            worker_rpc=RpcEndpoint("127.0.0.1", 50052),
            work_root=self.root / "jobs",
            attestation_transport=transport,
            attestation_resolver=self.resolver,
            id_factory=lambda: "job-shared-cancel",
            runner=cancelled_runner,
        )

        with self.assertRaisesRegex(Exception, "shared request was cancelled"):
            backend.complete(
                model_id="test-model",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertEqual(self.store.get_job("job-shared-cancel").state, JobState.CANCELLED)
        self.assertEqual(transport.calls, 0)
        for reservation_id in backend._reservation_ids("job-shared-cancel"):
            self.assertEqual(
                self.store.get_reservation(reservation_id).state,
                ReservationState.RELEASED,
            )
