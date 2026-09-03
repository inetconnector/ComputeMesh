"""Internal-only encrypted transport for the local OpenAI compatibility proxy.

These routes are not a user API.  Applications use the standard OpenAI surface
on the trusted local proxy; only ciphertext and content-free admission metadata
cross this remote boundary.
"""
from __future__ import annotations

from http import HTTPStatus
from urllib.parse import urlparse

from services.gateway.confidential_owner_handler import ConfidentialOwnerGatewayHandler
from services.gateway.live_handler import LiveGatewayHandler
from services.gateway.security import MAX_REQUEST_PAYLOAD_BYTES


INTERNAL_CONFIDENTIAL_SESSION_PATH = "/internal/v1/confidential/sessions"
INTERNAL_CONFIDENTIAL_COMPLETION_PATH = "/internal/v1/confidential/chat/completions"
LEGACY_PUBLIC_CONFIDENTIAL_PATHS = frozenset(
    {
        "/v1/confidential/sessions",
        "/v1/confidential/chat/completions",
    }
)


class InternalConfidentialOwnerGatewayHandler(ConfidentialOwnerGatewayHandler):
    """Encrypted transport contract consumed only by the local OpenAI bridge."""

    def _handle_internal_confidential_session_create(self) -> None:
        if not self._check_rate_limit():
            return
        auth = self._authenticate_confidential_owner()
        if auth is None:
            return
        coordinator = self.confidential_coordinator
        if coordinator is None:
            self._send_error_response(
                "Confidential session admission is not configured",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        body = self._read_json_object(max_bytes=MAX_REQUEST_PAYLOAD_BYTES)
        if body is None:
            return
        expected = {
            "model",
            "privacy_class",
            "operation",
            "max_prompt_tokens",
            "max_completion_tokens",
        }
        if set(body) != expected:
            self._send_error_response(
                "Invalid protected transport session contract",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return
        model_id = body.get("model")
        privacy = body.get("privacy_class")
        operation = body.get("operation")
        max_prompt = body.get("max_prompt_tokens")
        max_completion = body.get("max_completion_tokens")
        if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 512:
            self._send_error_response("Invalid confidential model", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if privacy not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
            self._send_error_response("Invalid confidential privacy class", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        if operation != "chat_completion":
            self._send_error_response("Invalid protected OpenAI operation", "invalid_request_error", HTTPStatus.BAD_REQUEST)
            return
        for value in (max_prompt, max_completion):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1_000_000:
                self._send_error_response("Invalid confidential token reservation", "invalid_request_error", HTTPStatus.BAD_REQUEST)
                return
        try:
            admission = coordinator.open_session(
                account_id=auth.owner_id,
                model_id=model_id.strip(),
                privacy_class=privacy,
                operation="chat_completion",
                max_prompt_tokens=max_prompt,
                max_completion_tokens=max_completion,
            )
        except Exception:
            self._send_error_response(
                "Confidential session could not be admitted",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        self._send_json(
            {
                "object": "computemesh.internal.confidential.session",
                "account_id": auth.owner_id,
                "session": admission.provision.public_descriptor(),
                "max_customer_charge_micro_units": admission.max_quote.customer_charge_micro_units,
            },
            HTTPStatus.CREATED,
            {"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
        if clean_path in LEGACY_PUBLIC_CONFIDENTIAL_PATHS:
            self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)
            return
        if clean_path == INTERNAL_CONFIDENTIAL_SESSION_PATH:
            self._handle_internal_confidential_session_create()
            return
        if clean_path == INTERNAL_CONFIDENTIAL_COMPLETION_PATH:
            self._handle_owner_confidential_completion()
            return
        # Skip ConfidentialOwnerGatewayHandler.do_POST so its old public aliases
        # cannot become reachable through MRO.
        LiveGatewayHandler.do_POST(self)
