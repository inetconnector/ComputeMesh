"""Live gateway handler with cancellation and P0 protected-execution gating."""
from __future__ import annotations

from contextlib import nullcontext
from http import HTTPStatus
import json
from typing import Any, Callable
from urllib.parse import urlparse

from runtime.confidential.execution_gate import (
    ProtectedExecutionEvidence,
    ProtectedExecutionUnavailable,
    require_protected_execution,
)
from services.compliance.mesh_policy import ExecutionPrivacyClass
from services.gateway.cancellable_inference import CancellableInferenceEngine
from services.gateway.server import GatewayHandler
from services.gateway.security import MAX_REQUEST_PAYLOAD_BYTES


ProtectedEvidenceResolver = Callable[
    [ExecutionPrivacyClass, dict[str, Any]],
    ProtectedExecutionEvidence,
]


class LiveGatewayHandler(GatewayHandler):
    """Live gateway with account-bound cancellation and protected privacy gates.

    `protected_execution_evidence_resolver` must be installed by a real protected
    runtime before `CONFIDENTIAL` or `CRYPTO_PRIVATE` traffic can execute.  Its
    default is deliberately None, so merely requesting a protected class cannot
    route plaintext through the ordinary live backend.
    """

    inference_engine: CancellableInferenceEngine
    protected_execution_evidence_resolver: ProtectedEvidenceResolver | None = None

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
            # Do not leak verifier/runtime details to an unauthenticated caller.
            self._send_error_response(
                "Protected execution evidence could not be verified",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        return True

    def _handle_chat_completions(self, body: dict[str, Any]) -> None:
        if not self._enforce_protected_privacy(body):
            return
        try:
            scope = self._request_scope()
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        with scope:
            super()._handle_chat_completions(body)

    def _handle_ollama_chat(self, body: dict[str, Any]) -> None:
        if not self._enforce_protected_privacy(body):
            return
        try:
            scope = self._request_scope()
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        with scope:
            super()._handle_ollama_chat(body)

    def _handle_ollama_generate(self, body: dict[str, Any]) -> None:
        if not self._enforce_protected_privacy(body):
            return
        try:
            scope = self._request_scope()
        except ValueError as exc:
            self._send_error_response(str(exc), "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        with scope:
            super()._handle_ollama_generate(body)

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
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
            # Do not reveal whether the ID belongs to another account or is simply inactive.
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
