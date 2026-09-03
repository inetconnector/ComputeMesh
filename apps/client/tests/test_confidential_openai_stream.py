from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest

from apps.client.confidential_openai import LocalAttestationPolicy
from apps.client.confidential_openai_stream import StreamingConfidentialOpenAIBridge
from protocol.confidential_envelope import (
    ConfidentialEnvelope,
    decrypt_in_attested_recipient,
    generate_attested_recipient_keypair,
)
from protocol.confidential_request_contract import create_committed_attestation_nonce
from protocol.confidential_stream import encrypt_stream_event_in_attested_recipient
from services.common.secure_memory import secure_zero_memory


RUNTIME = "sha256:" + "a" * 64
TLS = "sha256:" + "b" * 64


class FakeStreamingTransport:
    def __init__(self) -> None:
        self.private_key, self.public_key = generate_attested_recipient_keypair()
        self.node_id = "node-stream-1"
        self.nonce = ""
        self.account_id = "owner-stream-1"
        self.last_plaintext_request = None
        self.remote_wire_repr = ""

    def create_session(self, **kwargs):
        now = datetime.now(UTC)
        self.nonce = create_committed_attestation_nonce(
            model_id=kwargs["model"],
            max_prompt_tokens=kwargs["max_prompt_tokens"],
            max_completion_tokens=kwargs["max_completion_tokens"],
            entropy=b"s" * 32,
        )
        attestation = {
            "schema_version": 1,
            "node_id": self.node_id,
            "technology": "test_tee",
            "measurement": "measurement",
            "runtime_digest": RUNTIME,
            "ephemeral_public_key": self.public_key,
            "metering_public_key": "meter-key",
            "data_plane_tls_sha256": TLS,
            "nonce": self.nonce,
            "issued_at": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "debug_disabled": True,
        }
        return {
            "account_id": self.account_id,
            "session": {
                "job_id": "job-stream-1",
                "model_id": kwargs["model"],
                "privacy_class": kwargs["privacy_class"],
                "operation": "chat_completion",
                "max_prompt_tokens": kwargs["max_prompt_tokens"],
                "max_completion_tokens": kwargs["max_completion_tokens"],
                "node_id": self.node_id,
                "runtime_digest": RUNTIME,
                "attestation_nonce": self.nonce,
                "recipient_public_key": self.public_key,
                "metering_public_key": "meter-key",
                "data_plane_tls_sha256": TLS,
                "attestation": attestation,
            },
        }

    def stream_execute(self, *, authorization, privacy_class, envelope):
        self.remote_wire_repr = repr(envelope)
        request = ConfidentialEnvelope.from_dict(envelope)
        plaintext = decrypt_in_attested_recipient(
            request,
            recipient_private_key=self.private_key,
            expected_binding=request.binding,
        )
        try:
            self.last_plaintext_request = json.loads(bytes(plaintext).decode("utf-8"))
        finally:
            secure_zero_memory(plaintext)
        chunks = [
            {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": self.last_plaintext_request["model"],
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": self.last_plaintext_request["model"],
                "choices": [{"index": 0, "delta": {"content": "secret token"}, "finish_reason": None}],
            },
        ]
        for sequence, chunk in enumerate(chunks):
            response = encrypt_stream_event_in_attested_recipient(
                request,
                sequence=sequence,
                done=False,
                chunk=chunk,
                recipient_private_key=self.private_key,
            )
            yield {"type": "chunk", "response": response.to_dict()}
        final = encrypt_stream_event_in_attested_recipient(
            request,
            sequence=len(chunks),
            done=True,
            chunk=None,
            recipient_private_key=self.private_key,
        )
        yield {"type": "done", "response": final.to_dict(), "billing_status": "completed"}

    def execute(self, **kwargs):
        raise AssertionError("non-stream execute should not be called")

    def get_models(self, **kwargs):
        return 200, b'{"object":"list","data":[]}', "application/json"


class StreamingBridgeTests(unittest.TestCase):
    def test_true_encrypted_stream_becomes_openai_sse_only_locally(self) -> None:
        transport = FakeStreamingTransport()
        bridge = StreamingConfidentialOpenAIBridge(
            transport=transport,
            attestation_policy=LocalAttestationPolicy(
                verifiers={"test_tee": lambda record: True},
                allowed_runtime_digests=frozenset({RUNTIME}),
            ),
        )
        body = {
            "model": "model-a",
            "messages": [{"role": "user", "content": "SECRET STREAM PROMPT"}],
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "private_tool"}}],
        }
        output = b"".join(bridge.stream(authorization="Bearer key", body=body))
        self.assertEqual(transport.last_plaintext_request, body)
        self.assertNotIn("SECRET STREAM PROMPT", transport.remote_wire_repr)
        self.assertNotIn("private_tool", transport.remote_wire_repr)
        self.assertIn(b'"object":"chat.completion.chunk"', output)
        self.assertIn(b"secret token", output)
        self.assertTrue(output.endswith(b"data: [DONE]\n\n"))

    def test_missing_final_frame_never_emits_done(self) -> None:
        class Truncated(FakeStreamingTransport):
            def stream_execute(self, **kwargs):
                events = list(super().stream_execute(**kwargs))
                yield from events[:-1]

        transport = Truncated()
        bridge = StreamingConfidentialOpenAIBridge(
            transport=transport,
            attestation_policy=LocalAttestationPolicy(
                verifiers={"test_tee": lambda record: True},
                allowed_runtime_digests=frozenset({RUNTIME}),
            ),
        )
        with self.assertRaises(Exception):
            list(
                bridge.stream(
                    authorization="Bearer key",
                    body={"model": "model-a", "messages": [], "stream": True},
                )
            )


if __name__ == "__main__":
    unittest.main()
