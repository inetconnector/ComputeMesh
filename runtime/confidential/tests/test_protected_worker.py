from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    create_confidential_request,
    decrypt_confidential_response,
)
from protocol.confidential_metering import verify_confidential_usage_receipt
from protocol.confidential_request_contract import verify_committed_session_attestation_nonce
from protocol.confidential_stream import decrypt_stream_event
from runtime.confidential.protected_worker import ProtectedWorkerError, ProtectedWorkerSessionManager
from runtime.confidential.replay_store import SQLiteConfidentialReplayStore
from services.common.secure_memory import secure_zero_memory


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
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "secret answer"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        }

    def stream(self, request):
        yield {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": request["model"],
            "choices": [{"index": 0, "delta": {"content": "secret"}, "finish_reason": None}],
        }
        yield {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": request["model"],
            "choices": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }


class ProtectedWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = ProtectedWorkerSessionManager(
            node_id="node-1",
            runtime_digest="sha256:runtime-1",
            worker_url="https://worker.example/internal/v1/confidential/execute",
            data_plane_tls_sha256="sha256:" + "a" * 64,
            replay_store=SQLiteConfidentialReplayStore(Path(self.tmp.name) / "replay.sqlite3"),
            backend=_Backend(),
            attestation_issuer=_Issuer(),
        )
        self.challenge = b"z" * 32
        self.base_request = {
            "account_id": "owner-1",
            "job_id": "job-1",
            "model_id": "model-1",
            "privacy_class": "CONFIDENTIAL",
            "operation": "chat_completion",
            "max_prompt_tokens": 1024,
            "max_completion_tokens": 128,
        }

    def _provision(self, *, job_id: str = "job-1"):
        request = {**self.base_request, "job_id": job_id}
        provision = self.manager.provision(request, freshness_challenge=self.challenge)
        endpoint = provision["endpoint"]
        verify_committed_session_attestation_nonce(
            endpoint["attestation_nonce"],
            account_id=request["account_id"],
            job_id=request["job_id"],
            model_id=request["model_id"],
            max_prompt_tokens=request["max_prompt_tokens"],
            max_completion_tokens=request["max_completion_tokens"],
            node_id=endpoint["node_id"],
            runtime_digest=endpoint["runtime_digest"],
            recipient_public_key=endpoint["recipient_public_key"],
            metering_public_key=endpoint["metering_public_key"],
            data_plane_tls_sha256=endpoint["tls_certificate_sha256"],
            privacy_class=request["privacy_class"],
            operation=request["operation"],
            expected_entropy=self.challenge,
        )
        binding = ConfidentialBinding(
            account_id=request["account_id"],
            job_id=request["job_id"],
            node_id=endpoint["node_id"],
            attestation_nonce=endpoint["attestation_nonce"],
            runtime_digest=endpoint["runtime_digest"],
            data_plane_tls_sha256=endpoint["tls_certificate_sha256"],
            privacy_class=request["privacy_class"],
            operation=request["operation"],
        )
        return request, provision, binding

    def test_provision_commits_complete_session_and_never_returns_private_keys(self):
        _, provision, _ = self._provision()
        serialized = json.dumps(provision, sort_keys=True)
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("recipient_private", serialized)
        self.assertNotIn("metering_private", serialized)
        self.assertEqual(provision["attestation"]["job_id"], "job-1")
        self.assertEqual(provision["attestation"]["debug_disabled"], True)

    def test_nonstream_round_trip_and_signed_usage(self):
        request, provision, binding = self._provision()
        plaintext = json.dumps(
            {"model": request["model_id"], "messages": [{"role": "user", "content": "secret"}]},
            separators=(",", ":"),
        ).encode()
        envelope, context = create_confidential_request(
            plaintext,
            recipient_public_key=provision["endpoint"]["recipient_public_key"],
            binding=binding,
        )
        try:
            result = self.manager.execute(envelope)
            recovered = decrypt_confidential_response(result.response, client_context=context)
            try:
                response = json.loads(bytes(recovered).decode())
            finally:
                secure_zero_memory(recovered)
            self.assertEqual(response["choices"][0]["message"]["content"], "secret answer")
            receipt = verify_confidential_usage_receipt(
                result.usage_receipt,
                attested_metering_public_key=provision["endpoint"]["metering_public_key"],
                expected_account_id=request["account_id"],
                expected_job_id=request["job_id"],
                expected_request_envelope_id=envelope.envelope_id,
                expected_response_id=result.response.response_id,
                expected_node_id="node-1",
                expected_runtime_digest="sha256:runtime-1",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
                expected_model_id="model-1",
                max_prompt_tokens=1024,
                max_completion_tokens=128,
            )
            self.assertEqual((receipt.prompt_tokens, receipt.completion_tokens), (7, 3))
        finally:
            context.close()

    def test_same_attested_session_is_one_shot(self):
        request, provision, binding = self._provision()
        envelope, context = create_confidential_request(
            json.dumps({"model": request["model_id"], "messages": []}).encode(),
            recipient_public_key=provision["endpoint"]["recipient_public_key"],
            binding=binding,
        )
        try:
            self.manager.execute(envelope)
            with self.assertRaisesRegex(ProtectedWorkerError, "already consumed"):
                self.manager.execute(envelope)
        finally:
            context.close()

    def test_stream_frames_are_encrypted_ordered_and_final_receipt_is_bound(self):
        request, provision, binding = self._provision(job_id="job-stream")
        envelope, context = create_confidential_request(
            json.dumps({"model": request["model_id"], "messages": [], "stream": True}).encode(),
            recipient_public_key=provision["endpoint"]["recipient_public_key"],
            binding=binding,
        )
        try:
            results = list(self.manager.stream(envelope))
            self.assertEqual(len(results), 3)
            first = decrypt_stream_event(results[0].response, client_context=context, expected_sequence=0)
            second = decrypt_stream_event(results[1].response, client_context=context, expected_sequence=1)
            final = decrypt_stream_event(results[2].response, client_context=context, expected_sequence=2)
            self.assertFalse(first.done)
            self.assertFalse(second.done)
            self.assertTrue(final.done)
            self.assertIsNone(results[0].usage_receipt)
            self.assertIsNone(results[1].usage_receipt)
            self.assertIsNotNone(results[2].usage_receipt)
            assert results[2].usage_receipt is not None
            verify_confidential_usage_receipt(
                results[2].usage_receipt,
                attested_metering_public_key=provision["endpoint"]["metering_public_key"],
                expected_account_id=request["account_id"],
                expected_job_id=request["job_id"],
                expected_request_envelope_id=envelope.envelope_id,
                expected_response_id=results[2].response.response_id,
                expected_node_id="node-1",
                expected_runtime_digest="sha256:runtime-1",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
                expected_model_id="model-1",
                max_prompt_tokens=1024,
                max_completion_tokens=128,
            )
        finally:
            context.close()

    def test_crypto_private_is_not_silently_downgraded_to_tee_path(self):
        with self.assertRaisesRegex(ProtectedWorkerError, "CONFIDENTIAL only"):
            self.manager.provision(
                {**self.base_request, "privacy_class": "CRYPTO_PRIVATE"},
                freshness_challenge=self.challenge,
            )


if __name__ == "__main__":
    unittest.main()
