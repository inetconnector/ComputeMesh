from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from protocol.confidential_envelope import ConfidentialBinding, create_confidential_request
from runtime.confidential.protected_worker import ProtectedWorkerError, ProtectedWorkerSessionManager
from runtime.confidential.replay_store import SQLiteConfidentialReplayStore


class _Issuer:
    def issue(self, *, node_id: str, nonce: str):
        return {
            "technology": "vendor-tee-v1",
            "measurement": "measurement-1",
            "vendor_evidence": {"opaque": "evidence"},
            "debug_disabled": True,
        }


class _Backend:
    def complete(self, request):
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": request["model"],
            "choices": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def stream(self, request):
        yield {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": request["model"],
            "choices": [{"index": 0, "delta": {"content": "x"}, "finish_reason": None}],
        }
        yield {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": request["model"],
            "choices": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }


class _FailingBackend(_Backend):
    def complete(self, request):
        raise RuntimeError("backend failed")


class ProtectedWorkerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.challenge = b"q" * 32

    def _manager(self, backend=None, *, max_active_sessions=1):
        return ProtectedWorkerSessionManager(
            node_id="node-1",
            runtime_digest="sha256:runtime-1",
            worker_url="https://worker.example/internal/v1/confidential/execute",
            data_plane_tls_sha256="sha256:" + "a" * 64,
            replay_store=SQLiteConfidentialReplayStore(Path(self.tmp.name) / "replay.sqlite3"),
            backend=backend or _Backend(),
            attestation_issuer=_Issuer(),
            max_active_sessions=max_active_sessions,
        )

    @staticmethod
    def _request(job_id: str):
        return {
            "account_id": "owner-1",
            "job_id": job_id,
            "model_id": "model-1",
            "privacy_class": "CONFIDENTIAL",
            "operation": "chat_completion",
            "max_prompt_tokens": 32,
            "max_completion_tokens": 16,
        }

    def _envelope(self, manager, job_id: str, *, stream=False):
        request = self._request(job_id)
        provision = manager.provision(request, freshness_challenge=self.challenge)
        endpoint = provision["endpoint"]
        binding = ConfidentialBinding(
            account_id=request["account_id"],
            job_id=job_id,
            node_id=endpoint["node_id"],
            attestation_nonce=endpoint["attestation_nonce"],
            runtime_digest=endpoint["runtime_digest"],
            data_plane_tls_sha256=endpoint["tls_certificate_sha256"],
            privacy_class=request["privacy_class"],
            operation=request["operation"],
        )
        payload = {"model": "model-1", "messages": []}
        if stream:
            payload["stream"] = True
        envelope, context = create_confidential_request(
            json.dumps(payload).encode(),
            recipient_public_key=endpoint["recipient_public_key"],
            binding=binding,
        )
        self.addCleanup(context.close)
        return envelope

    def test_capacity_is_fail_closed_until_session_retires(self):
        manager = self._manager(max_active_sessions=1)
        envelope = self._envelope(manager, "job-1")
        self.assertEqual(manager.active_session_count(), 1)
        with self.assertRaisesRegex(ProtectedWorkerError, "capacity is exhausted"):
            manager.provision(self._request("job-2"), freshness_challenge=self.challenge)
        manager.execute(envelope)
        self.assertEqual(manager.active_session_count(), 0)
        manager.provision(self._request("job-2"), freshness_challenge=self.challenge)
        self.assertEqual(manager.active_session_count(), 1)

    def test_backend_failure_retires_request_scoped_key_state(self):
        manager = self._manager(_FailingBackend())
        envelope = self._envelope(manager, "job-fail")
        with self.assertRaisesRegex(RuntimeError, "backend failed"):
            manager.execute(envelope)
        self.assertEqual(manager.active_session_count(), 0)

    def test_stream_close_retires_session_even_without_normal_final_frame(self):
        manager = self._manager()
        envelope = self._envelope(manager, "job-stream", stream=True)
        iterator = manager.stream(envelope)
        next(iterator)
        self.assertEqual(manager.active_session_count(), 1)
        iterator.close()
        self.assertEqual(manager.active_session_count(), 0)

    def test_close_prevents_new_provision_and_drops_waiting_sessions(self):
        manager = self._manager(max_active_sessions=2)
        manager.provision(self._request("job-1"), freshness_challenge=self.challenge)
        self.assertEqual(manager.active_session_count(), 1)
        manager.close()
        self.assertEqual(manager.active_session_count(), 0)
        with self.assertRaisesRegex(ProtectedWorkerError, "closed"):
            manager.provision(self._request("job-2"), freshness_challenge=self.challenge)


if __name__ == "__main__":
    unittest.main()
