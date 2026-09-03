from __future__ import annotations

from io import BytesIO
from http import HTTPStatus
import json
import unittest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    create_confidential_request,
    encrypt_response_in_attested_recipient,
    generate_attested_recipient_keypair,
)
from runtime.confidential.data_plane import AttestedConfidentialEndpoint
from runtime.confidential.execution_gate import ProtectedExecutionEvidence
from runtime.confidential.replay_store import ConfidentialReplayDetected
from services.gateway.auth import AuthResult
from services.gateway.live_handler import LiveGatewayHandler


class _Auth:
    def __init__(self, account_id: str = "acct-1") -> None:
        self.account_id = account_id

    def authenticate_request(self, headers, client_address, allow_teaser=False):
        return AuthResult(account_id=self.account_id)


class _Replay:
    def __init__(self, *, replay: bool = False) -> None:
        self.replay = replay
        self.calls = []

    def claim(self, envelope, **kwargs):
        self.calls.append((envelope, kwargs))
        if self.replay:
            raise ConfidentialReplayDetected("confidential envelope was already consumed")
        return object()


class _DataPlane:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    def execute(self, envelope, *, endpoint):
        self.calls.append((envelope, endpoint))
        return self.response


class LiveConfidentialTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recipient_private, self.recipient_public = generate_attested_recipient_keypair()
        self.tls_fingerprint = "sha256:" + "a" * 64
        self.binding = ConfidentialBinding(
            account_id="acct-1",
            job_id="job-1",
            node_id="node-1",
            attestation_nonce="nonce-1",
            runtime_digest="sha256:runtime",
            data_plane_tls_sha256=self.tls_fingerprint,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
        )
        self.envelope, self.client_context = create_confidential_request(
            b'{"model":"secret-model","messages":[{"role":"user","content":"NEVER-GATEWAY"}]}',
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        self.response = encrypt_response_in_attested_recipient(
            self.envelope,
            b'{"choices":[{"message":{"content":"NEVER-GATEWAY-OUTPUT"}}]}',
            recipient_private_key=self.recipient_private,
        )
        self.endpoint = AttestedConfidentialEndpoint(
            url="https://tee.example/v1/confidential/execute",
            node_id="node-1",
            runtime_digest="sha256:runtime",
            attestation_nonce="nonce-1",
            recipient_public_key=self.recipient_public,
            metering_public_key="metering-key-1",
            tls_certificate_sha256=self.tls_fingerprint,
        )

    def tearDown(self) -> None:
        self.client_context.close()

    @staticmethod
    def _ready() -> ProtectedExecutionEvidence:
        return ProtectedExecutionEvidence(
            attestation_verified=True,
            attestation_fresh=True,
            debug_disabled=True,
            runtime_measurement_bound=True,
            ephemeral_key_bound=True,
            content_key_release_bound=True,
            encrypted_data_plane=True,
            protected_memory=True,
            plaintext_logging_disabled=True,
            blinded_split_validated=True,
        )

    def _handler(self, *, account_id: str = "acct-1", replay: bool = False):
        handler = object.__new__(LiveGatewayHandler)
        body = json.dumps(
            {
                "computemesh_privacy": "CONFIDENTIAL",
                "envelope": self.envelope.to_dict(),
            }
        ).encode("utf-8")
        handler.headers = {
            "Content-Length": str(len(body)),
            "X-ComputeMesh-Request-ID": "job-1",
            "Authorization": "Bearer test-token",
        }
        handler.rfile = BytesIO(body)
        handler.client_address = ("127.0.0.1", 12345)
        handler.auth_manager = _Auth(account_id)
        handler._check_rate_limit = lambda: True
        errors = []
        responses = []
        handler._send_error_response = lambda message, kind, status: errors.append(  # type: ignore[method-assign]
            (message, kind, int(status))
        )
        handler._send_json = lambda value, status=HTTPStatus.OK, extra_headers=None: responses.append(  # type: ignore[method-assign]
            (value, int(status), extra_headers)
        )
        handler.protected_execution_evidence_resolver = lambda privacy, resolver_body: self._ready()
        handler.protected_endpoint_resolver = lambda privacy, envelope: self.endpoint
        replay_store = _Replay(replay=replay)
        data_plane = _DataPlane(self.response)
        handler.confidential_replay_store = replay_store
        handler.confidential_data_plane = data_plane
        return handler, errors, responses, replay_store, data_plane

    def test_plaintext_protected_request_is_never_admitted_to_normal_api(self) -> None:
        handler, errors, *_ = self._handler()
        self.assertFalse(
            handler._allow_plaintext_public_only(
                {
                    "computemesh_privacy": "CONFIDENTIAL",
                    "messages": [{"role": "user", "content": "plaintext-secret"}],
                }
            )
        )
        self.assertEqual(errors[-1][1], "protected_payload_requires_encryption")
        self.assertEqual(errors[-1][2], HTTPStatus.BAD_REQUEST)

    def test_ready_encrypted_request_claims_replay_before_dispatch_and_returns_only_ciphertext(self) -> None:
        handler, errors, responses, replay_store, data_plane = self._handler()
        handler._handle_confidential_chat_completion()
        self.assertEqual(errors, [])
        self.assertEqual(len(replay_store.calls), 1)
        self.assertEqual(len(data_plane.calls), 1)
        self.assertEqual(responses[-1][1], HTTPStatus.OK)
        payload = responses[-1][0]
        encoded = repr(payload)
        self.assertNotIn("NEVER-GATEWAY", encoded)
        self.assertNotIn("NEVER-GATEWAY-OUTPUT", encoded)
        self.assertEqual(payload["response"]["ciphertext"], self.response.ciphertext)
        self.assertEqual(responses[-1][2]["Cache-Control"], "no-store")

    def test_wrong_authenticated_account_fails_before_replay_or_dispatch(self) -> None:
        handler, errors, _, replay_store, data_plane = self._handler(account_id="acct-attacker")
        handler._handle_confidential_chat_completion()
        self.assertEqual(errors[-1][1], "invalid_confidential_envelope")
        self.assertEqual(replay_store.calls, [])
        self.assertEqual(data_plane.calls, [])

    def test_request_id_must_equal_encrypted_job_id(self) -> None:
        handler, errors, _, replay_store, data_plane = self._handler()
        handler.headers["X-ComputeMesh-Request-ID"] = "job-attacker"
        handler._handle_confidential_chat_completion()
        self.assertEqual(errors[-1][1], "invalid_confidential_envelope")
        self.assertEqual(replay_store.calls, [])
        self.assertEqual(data_plane.calls, [])

    def test_missing_protected_component_fails_before_replay(self) -> None:
        handler, errors, _, replay_store, data_plane = self._handler()
        handler.confidential_data_plane = None
        handler._handle_confidential_chat_completion()
        self.assertEqual(errors[-1][1], "confidential_execution_unavailable")
        self.assertEqual(errors[-1][2], HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertEqual(replay_store.calls, [])
        self.assertEqual(data_plane.calls, [])

    def test_replayed_request_never_reaches_data_plane(self) -> None:
        handler, errors, _, replay_store, data_plane = self._handler(replay=True)
        handler._handle_confidential_chat_completion()
        self.assertEqual(len(replay_store.calls), 1)
        self.assertEqual(errors[-1][1], "confidential_replay_detected")
        self.assertEqual(errors[-1][2], HTTPStatus.CONFLICT)
        self.assertEqual(data_plane.calls, [])

    def test_evidence_failure_happens_before_replay_claim(self) -> None:
        handler, errors, _, replay_store, data_plane = self._handler()
        incomplete = self._ready()
        handler.protected_execution_evidence_resolver = lambda privacy, body: ProtectedExecutionEvidence(
            **{**incomplete.__dict__, "attestation_verified": False}
        )
        handler._handle_confidential_chat_completion()
        self.assertEqual(errors[-1][1], "confidential_execution_unavailable")
        self.assertEqual(replay_store.calls, [])
        self.assertEqual(data_plane.calls, [])

    def test_endpoint_substitution_fails_before_replay_claim(self) -> None:
        handler, errors, _, replay_store, data_plane = self._handler()
        wrong = AttestedConfidentialEndpoint(
            **{**self.endpoint.__dict__, "node_id": "node-attacker"}
        )
        handler.protected_endpoint_resolver = lambda privacy, envelope: wrong
        handler._handle_confidential_chat_completion()
        self.assertEqual(errors[-1][1], "confidential_execution_unavailable")
        self.assertEqual(replay_store.calls, [])
        self.assertEqual(data_plane.calls, [])


if __name__ == "__main__":
    unittest.main()
