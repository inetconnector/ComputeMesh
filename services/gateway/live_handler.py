"""Live gateway with cancellation and fail-closed encrypted protected execution."""
from __future__ import annotations

from contextlib import nullcontext
from http import HTTPStatus
import json
from typing import Any, Callable
from urllib.parse import urlparse

from protocol.confidential_envelope import (
    MAX_CIPHERTEXT_BYTES,
    ConfidentialEnvelope,
    ConfidentialEnvelopeError,
)
from runtime.confidential.data_plane import (
    AttestedConfidentialEndpoint,
    ConfidentialDataPlane,
    ConfidentialDataPlaneError,
)
from runtime.confidential.execution_gate import (
    ProtectedExecutionEvidence,
    ProtectedExecutionUnavailable,
    require_protected_execution,
)
from runtime.confidential.replay_store import (
    ConfidentialReplayBindingError,
    ConfidentialReplayDetected,
    ConfidentialReplayStore,
)
from services.compliance.mesh_policy import ExecutionPrivacyClass
from services.gateway.cancellable_inference import CancellableInferenceEngine
from services.gateway.server import GatewayHandler
from services.gateway.security import MAX_REQUEST_PAYLOAD_BYTES


ProtectedEvidenceResolver = Callable[
    [ExecutionPrivacyClass, dict[str, Any]],
    ProtectedExecutionEvidence,
]
ProtectedEndpointResolver = Callable[
    [ExecutionPrivacyClass, ConfidentialEnvelope],
    AttestedConfidentialEndpoint,
]

# Base64 expansion plus bounded JSON framing around the 8 MiB encrypted payload.
MAX_CONFIDENTIAL_HTTP_BYTES = (MAX_CIPHERTEXT_BYTES * 4 // 3) + 512 * 1024


class LiveGatewayHandler(GatewayHandler):
    """Live gateway with public plaintext APIs and a separate opaque protected API.

    Protected payloads are categorically rejected on ordinary OpenAI/Ollama
    endpoints.  `CONFIDENTIAL` and `CRYPTO_PRIVATE` execute only through
    `/v1/confidential/chat/completions`, which accepts a v2 encrypted envelope and
    requires a real evidence resolver, attested endpoint resolver, durable replay
    store and encrypted data plane.  All four default to None (fail closed).
    """

    inference_engine: CancellableInferenceEngine
    protected_execution_evidence_resolver: ProtectedEvidenceResolver | None = None
    protected_endpoint_resolver: ProtectedEndpointResolver | None = None
    confidential_replay_store: ConfidentialReplayStore | None = None
    confidential_data_plane: ConfidentialDataPlane | None = None

    def _request_scope(self):
        request_id = self.headers.get("X-ComputeMesh-Request-ID", "").strip()
        if not request_id:
            return nullcontext()
        return self.inference_engine.request_scope(request_id)

    @staticmethod
    def _requested_privacy_class(body: dict[str, Any]) -> ExecutionPrivacyClass:
        value: Any = body.get("computemesh_privacy", ExecutionPrivacyClass.PUBLIC.value)
        if isinstance(value, dict):
            value = value.get("class", ExecutionPrivacyClass.PUBLIC.value)
        if not isinstance(value, str):
            raise ValueError("computemesh_privacy must be PUBLIC, CONFIDENTIAL or CRYPTO_PRIVATE")
        try:
            return ExecutionPrivacyClass(value.strip().upper())
        except ValueError as exc:
            raise ValueError(
                "computemesh_privacy must be PUBLIC, CONFIDENTIAL or CRYPTO_PRIVATE"
            ) from exc

    def _enforce_protected_privacy(self, body: dict[str, Any]) -> bool:
        """Evaluate request-scoped protected evidence for the encrypted route only."""
        try:
            privacy_class = self._requested_privacy_class(body)
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return False

        if privacy_class is ExecutionPrivacyClass.PUBLIC:
            return True

        resolver = self.protected_execution_evidence_resolver
        if resolver is None:
            self._send_error_response(
                "Protected execution is unavailable because the complete confidential runtime chain is not installed",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        try:
            evidence = resolver(privacy_class, body)
            require_protected_execution(privacy_class, evidence)
        except ProtectedExecutionUnavailable as exc:
            self._send_error_response(
                str(exc),
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        except Exception:
            self._send_error_response(
                "Protected execution evidence could not be verified",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        return True

    def _allow_plaintext_public_only(self, body: dict[str, Any]) -> bool:
        try:
            privacy_class = self._requested_privacy_class(body)
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return False
        if privacy_class is not ExecutionPrivacyClass.PUBLIC:
            self._send_error_response(
                "Protected requests must use /v1/confidential/chat/completions with a v2 encrypted envelope",
                "protected_payload_requires_encryption",
                HTTPStatus.BAD_REQUEST,
            )
            return False
        return True

    def _handle_chat_completions(self, body: dict[str, Any]) -> None:
        if not self._allow_plaintext_public_only(body):
            return
        try:
            scope = self._request_scope()
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        with scope:
            super()._handle_chat_completions(body)

    def _handle_ollama_chat(self, body: dict[str, Any]) -> None:
        if not self._allow_plaintext_public_only(body):
            return
        try:
            scope = self._request_scope()
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        with scope:
            super()._handle_ollama_chat(body)

    def _handle_ollama_generate(self, body: dict[str, Any]) -> None:
        if not self._allow_plaintext_public_only(body):
            return
        try:
            scope = self._request_scope()
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        with scope:
            super()._handle_ollama_generate(body)

    def _read_confidential_body(self) -> dict[str, Any] | None:
        raw_length = self.headers.get("Content-Length", "")
        try:
            content_length = int(raw_length)
        except ValueError:
            self._send_error_response("Invalid Content-Length header", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return None
        if content_length <= 0 or content_length > MAX_CONFIDENTIAL_HTTP_BYTES:
            self._send_error_response(
                "Invalid confidential request payload size",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        try:
            value = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._send_error_response("Malformed confidential JSON request body", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(value, dict) or set(value) != {"computemesh_privacy", "envelope"}:
            self._send_error_response(
                "Invalid confidential request contract",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        return value

    def _handle_confidential_chat_completion(self) -> None:
        if not self._check_rate_limit():
            return
        auth = self.auth_manager.authenticate_request(
            self.headers,
            getattr(self, "client_address", None),
            allow_teaser=False,
        )
        if not auth.is_authenticated or not auth.account_id:
            self._send_error_response(
                auth.error_message or "Unauthorized",
                "authentication_error",
                auth.status_code,
            )
            return
        body = self._read_confidential_body()
        if body is None:
            return
        try:
            privacy_class = self._requested_privacy_class(body)
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if privacy_class is ExecutionPrivacyClass.PUBLIC:
            self._send_error_response(
                "PUBLIC requests must use the ordinary API",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return
        envelope_value = body.get("envelope")
        if not isinstance(envelope_value, dict):
            self._send_error_response("Confidential envelope is required", "invalid_confidential_envelope", HTTPStatus.BAD_REQUEST)
            return
        try:
            envelope = ConfidentialEnvelope.from_dict(envelope_value)
        except ConfidentialEnvelopeError:
            self._send_error_response(
                "Confidential envelope is invalid",
                "invalid_confidential_envelope",
                HTTPStatus.BAD_REQUEST,
            )
            return

        binding = envelope.binding
        if binding.account_id != auth.account_id:
            self._send_error_response("Confidential account binding mismatch", "invalid_confidential_envelope", HTTPStatus.BAD_REQUEST)
            return
        if binding.privacy_class != privacy_class.value:
            self._send_error_response("Confidential privacy binding mismatch", "invalid_confidential_envelope", HTTPStatus.BAD_REQUEST)
            return
        if binding.operation != "chat_completion":
            self._send_error_response("Confidential operation binding mismatch", "invalid_confidential_envelope", HTTPStatus.BAD_REQUEST)
            return
        request_id = self.headers.get("X-ComputeMesh-Request-ID", "").strip()
        if not request_id or request_id != binding.job_id:
            self._send_error_response(
                "X-ComputeMesh-Request-ID must equal the encrypted job binding",
                "invalid_confidential_envelope",
                HTTPStatus.BAD_REQUEST,
            )
            return

        endpoint_resolver = self.protected_endpoint_resolver
        replay_store = self.confidential_replay_store
        data_plane = self.confidential_data_plane
        if endpoint_resolver is None or replay_store is None or data_plane is None:
            self._send_error_response(
                "Protected execution transport is not fully configured",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        try:
            endpoint = endpoint_resolver(privacy_class, envelope)
            endpoint.assert_matches(envelope)
        except Exception:
            self._send_error_response(
                "Attested confidential endpoint could not be resolved",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return

        resolver_body = {
            "computemesh_privacy": privacy_class.value,
            "envelope": envelope.to_dict(),
            "attested_endpoint": {
                "node_id": endpoint.node_id,
                "runtime_digest": endpoint.runtime_digest,
                "attestation_nonce": endpoint.attestation_nonce,
                "recipient_public_key": endpoint.recipient_public_key,
                "tls_certificate_sha256": endpoint.tls_certificate_sha256,
            },
        }
        if not self._enforce_protected_privacy(resolver_body):
            return

        try:
            replay_store.claim(
                envelope,
                expected_account_id=auth.account_id,
                expected_privacy_class=privacy_class.value,
                expected_operation="chat_completion",
            )
        except ConfidentialReplayDetected:
            self._send_error_response(
                "Confidential envelope was already consumed",
                "confidential_replay_detected",
                HTTPStatus.CONFLICT,
            )
            return
        except ConfidentialReplayBindingError:
            self._send_error_response(
                "Confidential envelope binding mismatch",
                "invalid_confidential_envelope",
                HTTPStatus.BAD_REQUEST,
            )
            return
        except Exception:
            self._send_error_response(
                "Confidential replay protection is unavailable",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return

        try:
            protected_response = data_plane.execute(envelope, endpoint=endpoint)
        except ConfidentialDataPlaneError:
            self._send_error_response(
                "Confidential execution transport failed",
                "confidential_execution_failed",
                HTTPStatus.BAD_GATEWAY,
            )
            return
        except Exception:
            self._send_error_response(
                "Confidential execution failed",
                "confidential_execution_failed",
                HTTPStatus.BAD_GATEWAY,
            )
            return

        self._send_json(
            {
                "object": "confidential.chat.completion",
                "confidential_protocol_version": envelope.schema_version,
                "response": protected_response.to_dict(),
            },
            HTTPStatus.OK,
            {"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
        if clean_path == "/v1/confidential/chat/completions":
            self._handle_confidential_chat_completion()
            return
        if clean_path != "/v1/inference/cancel":
            super().do_POST()
            return

        if not self._check_rate_limit():
            return
        auth = self.auth_manager.authenticate_request(
            self.headers,
            getattr(self, "client_address", None),
            allow_teaser=False,
        )
        if not auth.is_authenticated or not auth.account_id:
            self._send_error_response(
                auth.error_message or "Unauthorized",
                "authentication_error",
                auth.status_code,
            )
            return
        raw_length = self.headers.get("Content-Length", "")
        try:
            content_length = int(raw_length)
        except ValueError:
            self._send_error_response("Invalid Content-Length header", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if content_length <= 0 or content_length > MAX_REQUEST_PAYLOAD_BYTES:
            self._send_error_response("Invalid cancellation payload size", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        try:
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._send_error_response("Malformed JSON request body", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(body, dict) or set(body) != {"request_id", "reason", "cutoff_policy"}:
            self._send_error_response("Invalid cancellation payload", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        request_id = body.get("request_id")
        reason = body.get("reason")
        cutoff = body.get("cutoff_policy")
        if not isinstance(request_id, str) or not isinstance(reason, str) or not (1 <= len(reason) <= 512):
            self._send_error_response("Invalid cancellation payload", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if cutoff != "stop_new_billable_work":
            self._send_error_response("Unsupported cancellation cutoff policy", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        try:
            cancelled = self.inference_engine.cancel_request(
                account_id=auth.account_id,
                request_id=request_id,
            )
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if not cancelled:
            self._send_error_response("Active request not found", "not_found", HTTPStatus.NOT_FOUND)
            return
        self._send_json(
            {
                "request_id": request_id,
                "status": "cancellation_requested",
                "cutoff_policy": "stop_new_billable_work",
            },
            HTTPStatus.ACCEPTED,
        )
