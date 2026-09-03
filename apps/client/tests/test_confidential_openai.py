from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest

from apps.client.confidential_openai import (
    ConfidentialOpenAIBridge,
    ConfidentialOpenAIError,
    LocalAttestationPolicy,
    is_loopback_host,
    prepare_openai_chat_request,
)
from protocol.confidential_envelope import (
    ConfidentialEnvelope,
    decrypt_in_attested_recipient,
    encrypt_response_in_attested_recipient,
    generate_attested_recipient_keypair,
)
from protocol.confidential_request_contract import create_committed_attestation_nonce
from services.common.secure_memory import secure_zero_memory


RUNTIME_DIGEST = "sha256:" + "a" * 64
TLS_DIGEST = "sha256:" + "b" * 64


class FakeProtectedTransport:
    def __init__(self) -> None:
        self.private_key, self.public_key = generate_attested_recipient_keypair()
        self.session_requests: list[dict] = []
        self.execute_requests: list[dict] = []
        self.decrypted_requests: list[dict] = []
        self.account_id = "owner-123"
        self.node_id = "node-tee-1"
        self.nonce = ""
        self.metering_public_key = "metering-key-123"

    def _attestation(self) -> dict:
        now = datetime.now(UTC)
        return {
            "schema_version": 1,
            "node_id": self.node_id,
            "technology": "test_tee",
            "measurement": "measurement-1",
            "runtime_digest": RUNTIME_DIGEST,
            "ephemeral_public_key": self.public_key,
            "metering_public_key": self.metering_public_key,
            "data_plane_tls_sha256": TLS_DIGEST,
            "nonce": self.nonce,
            "issued_at": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "debug_disabled": True,
        }

    def create_session(
        self,
        *,
        authorization: str,
        model: str,
        privacy_class: str,
        max_prompt_tokens: int,
        max_completion_tokens: int,
    ) -> dict:
        self.session_requests.append(
            {
                "authorization": authorization,
                "model": model,
                "privacy_class": privacy_class,
                "max_prompt_tokens": max_prompt_tokens,
                "max_completion_tokens": max_completion_tokens,
            }
        )
        self.nonce = create_committed_attestation_nonce(
            model_id=model,
            max_prompt_tokens=max_prompt_tokens,
            max_completion_tokens=max_completion_tokens,
            entropy=b"x" * 32,
        )
        attestation = self._attestation()
        return {
            "object": "computemesh.internal.confidential.session",
            "account_id": self.account_id,
            "session": {
                "schema_version": 1,
                "job_id": "job-123",
                "model_id": model,
                "privacy_class": privacy_class,
                "operation": "chat_completion",
                "max_prompt_tokens": max_prompt_tokens,
                "max_completion_tokens": max_completion_tokens,
                "expires_at": attestation["expires_at"],
                "node_id": self.node_id,
                "runtime_digest": RUNTIME_DIGEST,
                "attestation_nonce": self.nonce,
                "recipient_public_key": self.public_key,
                "metering_public_key": self.metering_public_key,
                "data_plane_tls_sha256": TLS_DIGEST,
                "attestation": attestation,
            },
            "max_customer_charge_micro_units": 1000,
        }

    def execute(self, *, authorization: str, privacy_class: str, envelope: dict) -> dict:
        self.execute_requests.append(
            {
                "authorization": authorization,
                "privacy_class": privacy_class,
                "envelope": envelope,
            }
        )
        parsed = ConfidentialEnvelope.from_dict(envelope)
        plaintext = decrypt_in_attested_recipient(
            parsed,
            recipient_private_key=self.private_key,
            expected_binding=parsed.binding,
        )
        try:
            request_body = json.loads(bytes(plaintext).decode("utf-8"))
            self.decrypted_requests.append(request_body)
        finally:
            secure_zero_memory(plaintext)
        response = {
            "id": "chatcmpl-protected-1",
            "object": "chat.completion",
            "created": 1700000000,
            "model": request_body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "secret answer",
                        "tool_calls": request_body.get("tools", []),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
        response_envelope = encrypt_response_in_attested_recipient(
            parsed,
            json.dumps(response, separators=(",", ":")).encode("utf-8"),
            recipient_private_key=self.private_key,
        )
        return {"response": response_envelope.to_dict(), "billing_status": "completed"}

    def get_models(self, *, authorization: str):
        return 200, b'{"object":"list","data":[]}', "application/json"


class ConfidentialOpenAIBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = FakeProtectedTransport()
        self.policy = LocalAttestationPolicy(
            verifiers={"test_tee": lambda record: True},
            allowed_runtime_digests=frozenset({RUNTIME_DIGEST}),
        )
        self.bridge = ConfidentialOpenAIBridge(
            transport=self.transport,
            attestation_policy=self.policy,
        )

    def test_original_openai_request_is_only_visible_inside_fake_tee(self) -> None:
        body = {
            "model": "qwen/qwen2.5-7b-instruct",
            "messages": [{"role": "user", "content": "TOP SECRET PROMPT"}],
            "temperature": 0.2,
            "top_p": 0.9,
            "response_format": {"type": "json_object"},
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "private tool description",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "tool_choice": "auto",
            "max_completion_tokens": 64,
        }
        result = self.bridge.complete(authorization="Bearer test-key", body=body)
        self.assertEqual(result["object"], "chat.completion")
        self.assertEqual(result["choices"][0]["message"]["content"], "secret answer")
        self.assertEqual(self.transport.decrypted_requests, [body])

        remote_view = json.dumps(
            {
                "session": self.transport.session_requests,
                "execute": self.transport.execute_requests,
            },
            sort_keys=True,
        )
        self.assertNotIn("TOP SECRET PROMPT", remote_view)
        self.assertNotIn("private tool description", remote_view)
        self.assertNotIn("secret answer", remote_view)

    def test_session_attestation_is_verified_locally(self) -> None:
        class BadTransport(FakeProtectedTransport):
            def _attestation(self) -> dict:
                value = super()._attestation()
                value["runtime_digest"] = "sha256:" + "c" * 64
                return value

        bridge = ConfidentialOpenAIBridge(
            transport=BadTransport(),
            attestation_policy=self.policy,
        )
        with self.assertRaisesRegex(ConfidentialOpenAIError, "binding mismatch"):
            bridge.complete(
                authorization="Bearer key",
                body={"model": "model-a", "messages": []},
            )

    def test_unapproved_runtime_fails_closed_before_encryption_dispatch(self) -> None:
        policy = LocalAttestationPolicy(
            verifiers={"test_tee": lambda record: True},
            allowed_runtime_digests=frozenset({"sha256:" + "d" * 64}),
        )
        bridge = ConfidentialOpenAIBridge(transport=self.transport, attestation_policy=policy)
        with self.assertRaisesRegex(ConfidentialOpenAIError, "not locally approved"):
            bridge.complete(
                authorization="Bearer key",
                body={"model": "model-a", "messages": []},
            )
        self.assertEqual(self.transport.execute_requests, [])

    def test_model_and_reservation_are_checked_before_dispatch(self) -> None:
        class WrongModelTransport(FakeProtectedTransport):
            def create_session(self, **kwargs):
                result = super().create_session(**kwargs)
                result["session"]["model_id"] = "other-model"
                return result

        transport = WrongModelTransport()
        bridge = ConfidentialOpenAIBridge(transport=transport, attestation_policy=self.policy)
        with self.assertRaisesRegex(ConfidentialOpenAIError, "model binding mismatch"):
            bridge.complete(
                authorization="Bearer key",
                body={"model": "model-a", "messages": []},
            )
        self.assertEqual(transport.execute_requests, [])

    def test_unbound_attestation_nonce_is_rejected_before_dispatch(self) -> None:
        class WrongContractTransport(FakeProtectedTransport):
            def create_session(self, **kwargs):
                result = super().create_session(**kwargs)
                bad_nonce = create_committed_attestation_nonce(
                    model_id="other-model",
                    max_prompt_tokens=kwargs["max_prompt_tokens"],
                    max_completion_tokens=kwargs["max_completion_tokens"],
                    entropy=b"z" * 32,
                )
                result["session"]["attestation_nonce"] = bad_nonce
                result["session"]["attestation"]["nonce"] = bad_nonce
                return result

        transport = WrongContractTransport()
        bridge = ConfidentialOpenAIBridge(transport=transport, attestation_policy=self.policy)
        with self.assertRaisesRegex(ConfidentialOpenAIError, "not attestation-bound"):
            bridge.complete(
                authorization="Bearer key",
                body={"model": "model-a", "messages": []},
            )
        self.assertEqual(transport.execute_requests, [])

    def test_stream_requires_encrypted_stream_transport_not_buffering(self) -> None:
        with self.assertRaises(ConfidentialOpenAIError) as captured:
            self.bridge.complete(
                authorization="Bearer key",
                body={"model": "model-a", "messages": [], "stream": True},
            )
        self.assertEqual(captured.exception.status, 501)
        self.assertEqual(captured.exception.code, "protected_stream_transport_required")
        self.assertEqual(self.transport.session_requests, [])

    def test_prepare_preserves_unknown_openai_fields(self) -> None:
        body = {
            "model": "model-a",
            "messages": [],
            "metadata": {"future": "field"},
            "parallel_tool_calls": True,
            "seed": 123,
        }
        prepared = prepare_openai_chat_request(body)
        self.assertEqual(json.loads(prepared.encoded.decode("utf-8")), body)

    def test_conflicting_token_limit_is_openai_shaped_invalid_request(self) -> None:
        with self.assertRaises(ConfidentialOpenAIError) as captured:
            prepare_openai_chat_request(
                {
                    "model": "model-a",
                    "messages": [],
                    "max_tokens": 10,
                    "max_completion_tokens": 20,
                }
            )
        self.assertEqual(captured.exception.status, 400)
        self.assertEqual(captured.exception.error_type, "invalid_request_error")

    def test_loopback_detection(self) -> None:
        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertFalse(is_loopback_host("0.0.0.0"))
        self.assertFalse(is_loopback_host("192.168.1.5"))


if __name__ == "__main__":
    unittest.main()
