"""Internal encrypted protected-transport routes for the canonical gateway.

This module is intentionally a pure mixin: it owns no HTTP server base class and
therefore can be composed with the live/cancellable gateway and unified-owner
billing handler without creating a second product server. Applications never call
these routes directly; the trusted local OpenAI proxy does.
"""
from __future__ import annotations

from http import HTTPStatus
import json
from typing import Any, Iterator
from urllib.parse import urlparse

from protocol.confidential_envelope import ConfidentialEnvelope, ConfidentialEnvelopeError
from protocol.confidential_metering import ConfidentialMeteringError
from runtime.confidential.data_plane import (
    ConfidentialDataPlane,
    ConfidentialDataPlaneError,
    ConfidentialDataPlaneResult,
)
from runtime.confidential.replay_store import (
    ConfidentialReplayBindingError,
    ConfidentialReplayDetected,
    ConfidentialReplayStore,
)
from runtime.confidential.session import ConfidentialSessionStateError
from runtime.confidential.stream_data_plane import PinnedHttpsConfidentialStreamDataPlane
from services.gateway.confidential_coordinator import (
    ConfidentialCoordinatorError,
    ConfidentialInferenceCoordinator,
)
from services.gateway.live_handler import MAX_CONFIDENTIAL_HTTP_BYTES
from services.gateway.security import MAX_REQUEST_PAYLOAD_BYTES


INTERNAL_CONFIDENTIAL_SESSION_PATH = "/internal/v1/confidential/sessions"
INTERNAL_CONFIDENTIAL_COMPLETION_PATH = "/internal/v1/confidential/chat/completions"
INTERNAL_CONFIDENTIAL_STREAM_PATH = "/internal/v1/confidential/chat/completions/stream"
LEGACY_PUBLIC_CONFIDENTIAL_PATHS = frozenset(
    {
        "/v1/confidential/sessions",
        "/v1/confidential/chat/completions",
        "/v1/confidential/chat/completions/stream",
    }
)


class ProtectedTransportMixin:
    """Ciphertext-only internal transport composed into the canonical gateway."""

    confidential_coordinator: ConfidentialInferenceCoordinator | None = None
    confidential_replay_store: ConfidentialReplayStore | None = None
    confidential_data_plane: ConfidentialDataPlane | None = None
    confidential_stream_data_plane: PinnedHttpsConfidentialStreamDataPlane | None = None

    def _authenticate_confidential_owner(self):
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
            return None
        if not auth.owner_id:
            self._send_error_response(
                "Confidential execution requires unified owner authentication",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return None
        return auth

    def _read_protected_json_object(self, *, max_bytes: int) -> dict[str, Any] | None:
        raw_length = self.headers.get("Content-Length", "")
        try:
            content_length = int(raw_length)
        except ValueError:
            self._send_error_response(
                "Invalid Content-Length header",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        if content_length <= 0 or content_length > max_bytes:
            self._send_error_response(
                "Invalid request payload size",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        try:
            value = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._send_error_response(
                "Malformed JSON request body",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        if not isinstance(value, dict):
            self._send_error_response(
                "Request body must be a JSON object",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        return value

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
        body = self._read_protected_json_object(max_bytes=MAX_REQUEST_PAYLOAD_BYTES)
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
            self._send_error_response(
                "Invalid confidential model",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return
        if privacy not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
            self._send_error_response(
                "Invalid confidential privacy class",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return
        if operation != "chat_completion":
            self._send_error_response(
                "Invalid protected OpenAI operation",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return
        for value in (max_prompt, max_completion):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1_000_000:
                self._send_error_response(
                    "Invalid confidential token reservation",
                    "invalid_request_error",
                    HTTPStatus.BAD_REQUEST,
                )
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

    @staticmethod
    def _assert_envelope_matches_session(envelope: ConfidentialEnvelope, session) -> None:
        binding = envelope.binding
        expected = {
            "account_id": session.account_id,
            "job_id": session.job_id,
            "node_id": session.node_id,
            "attestation_nonce": session.attestation_nonce,
            "runtime_digest": session.runtime_digest,
            "data_plane_tls_sha256": session.data_plane_tls_sha256,
            "privacy_class": session.privacy_class,
            "operation": session.operation,
        }
        for name, value in expected.items():
            if getattr(binding, name) != value:
                raise ConfidentialCoordinatorError(
                    f"confidential envelope {name} session mismatch"
                )
        session.endpoint.assert_matches(envelope)

    def _load_owner_envelope(self, *, auth, max_bytes: int):
        coordinator = self.confidential_coordinator
        replay_store = self.confidential_replay_store
        if coordinator is None or replay_store is None:
            self._send_error_response(
                "Confidential execution is not fully configured",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return None
        body = self._read_protected_json_object(max_bytes=max_bytes)
        if body is None:
            return None
        if set(body) != {"computemesh_privacy", "envelope"}:
            self._send_error_response(
                "Invalid confidential request contract",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        privacy_value = body.get("computemesh_privacy")
        if privacy_value not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
            self._send_error_response(
                "Invalid confidential privacy class",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        envelope_value = body.get("envelope")
        if not isinstance(envelope_value, dict):
            self._send_error_response(
                "Confidential envelope is required",
                "invalid_confidential_envelope",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        try:
            envelope = ConfidentialEnvelope.from_dict(envelope_value)
        except ConfidentialEnvelopeError:
            self._send_error_response(
                "Confidential envelope is invalid",
                "invalid_confidential_envelope",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        session = coordinator.session_store.get(envelope.binding.job_id)
        if session is None or session.account_id != auth.owner_id:
            self._send_error_response(
                "Confidential session not found",
                "not_found",
                HTTPStatus.NOT_FOUND,
            )
            return None
        if session.state != "OPEN":
            self._send_error_response(
                "Confidential session is not open",
                "confidential_session_state",
                HTTPStatus.CONFLICT,
            )
            return None
        try:
            self._assert_envelope_matches_session(envelope, session)
            reservation = coordinator.ledger.get_confidential_reservation(
                owner_id=session.account_id,
                reservation_id=session.hold_id,
            )
            if reservation is None or reservation.state != "reserved":
                raise ConfidentialCoordinatorError("confidential financial reservation is missing")
        except Exception:
            self._send_error_response(
                "Confidential session binding could not be verified",
                "invalid_confidential_envelope",
                HTTPStatus.BAD_REQUEST,
            )
            return None
        resolver_body = {
            "computemesh_privacy": privacy_value,
            "envelope": envelope.to_dict(),
            "attestation": dict(session.attestation),
            "attested_endpoint": {
                "node_id": session.node_id,
                "runtime_digest": session.runtime_digest,
                "attestation_nonce": session.attestation_nonce,
                "recipient_public_key": session.recipient_public_key,
                "metering_public_key": session.metering_public_key,
                "tls_certificate_sha256": session.data_plane_tls_sha256,
            },
        }
        if not self._enforce_protected_privacy(resolver_body):
            return None
        return coordinator, replay_store, privacy_value, envelope, session

    def _begin_protected_dispatch(self, *, coordinator, replay_store, envelope, session):
        try:
            session = coordinator.session_store.begin_dispatch(
                job_id=session.job_id,
                account_id=session.account_id,
                envelope_id=envelope.envelope_id,
            )
            replay_store.claim(
                envelope,
                expected_account_id=session.account_id,
                expected_privacy_class=session.privacy_class,
                expected_operation=session.operation,
            )
            return session
        except ConfidentialReplayDetected:
            self._send_error_response(
                "Confidential envelope was already consumed",
                "confidential_replay_detected",
                HTTPStatus.CONFLICT,
            )
        except (ConfidentialReplayBindingError, ConfidentialSessionStateError):
            self._send_error_response(
                "Confidential dispatch state is invalid",
                "confidential_session_state",
                HTTPStatus.CONFLICT,
            )
        except Exception:
            self._send_error_response(
                "Confidential replay protection is unavailable",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return None

    def _handle_internal_confidential_completion(self) -> None:
        if not self._check_rate_limit():
            return
        auth = self._authenticate_confidential_owner()
        if auth is None:
            return
        if self.confidential_data_plane is None:
            self._send_error_response(
                "Confidential execution is not fully configured",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        loaded = self._load_owner_envelope(auth=auth, max_bytes=MAX_CONFIDENTIAL_HTTP_BYTES)
        if loaded is None:
            return
        coordinator, replay_store, _privacy, envelope, session = loaded
        session = self._begin_protected_dispatch(
            coordinator=coordinator,
            replay_store=replay_store,
            envelope=envelope,
            session=session,
        )
        if session is None:
            return
        try:
            result = self.confidential_data_plane.execute(envelope, endpoint=session.endpoint)
            coordinator.verify_and_record_metering(session=session, data_plane_result=result)
        except (ConfidentialDataPlaneError, ConfidentialMeteringError, ConfidentialCoordinatorError):
            self._send_error_response(
                "Confidential execution evidence failed",
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

        billing_status = "completed"
        try:
            coordinator.settle_metered_session(job_id=session.job_id)
        except Exception:
            billing_status = "recovery_pending"
        self._send_json(
            {
                "object": "computemesh.internal.confidential.chat.completion",
                "confidential_protocol_version": envelope.schema_version,
                "billing_status": billing_status,
                "response": result.response.to_dict(),
            },
            HTTPStatus.OK,
            {"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    @staticmethod
    def _ndjson(value: dict) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"

    def _handle_internal_confidential_stream(self) -> None:
        if not self._check_rate_limit():
            return
        auth = self._authenticate_confidential_owner()
        if auth is None:
            return
        if self.confidential_stream_data_plane is None:
            self._send_error_response(
                "Confidential streaming execution is not fully configured",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        loaded = self._load_owner_envelope(auth=auth, max_bytes=MAX_CONFIDENTIAL_HTTP_BYTES)
        if loaded is None:
            return
        coordinator, replay_store, _privacy, envelope, session = loaded
        session = self._begin_protected_dispatch(
            coordinator=coordinator,
            replay_store=replay_store,
            envelope=envelope,
            session=session,
        )
        if session is None:
            return

        stream: Iterator = iter(
            self.confidential_stream_data_plane.stream_execute(envelope, endpoint=session.endpoint)
        )
        try:
            first = next(stream)
        except StopIteration:
            self._send_error_response(
                "Confidential stream ended before producing evidence",
                "confidential_execution_failed",
                HTTPStatus.BAD_GATEWAY,
            )
            return
        except ConfidentialDataPlaneError:
            self._send_error_response(
                "Confidential streaming data plane failed",
                "confidential_execution_failed",
                HTTPStatus.BAD_GATEWAY,
            )
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def events():
            yield first
            yield from stream

        done_seen = False
        try:
            for event in events():
                if done_seen:
                    raise ConfidentialDataPlaneError("stream produced data after final evidence")
                if not event.done:
                    self.wfile.write(
                        self._ndjson({"type": "chunk", "response": event.response.to_dict()})
                    )
                    self.wfile.flush()
                    continue
                if event.usage_receipt is None:
                    raise ConfidentialDataPlaneError("final stream evidence has no usage receipt")
                result = ConfidentialDataPlaneResult(
                    response=event.response,
                    usage_receipt=event.usage_receipt,
                )
                coordinator.verify_and_record_metering(session=session, data_plane_result=result)
                billing_status = "completed"
                try:
                    coordinator.settle_metered_session(job_id=session.job_id)
                except Exception:
                    billing_status = "recovery_pending"
                self.wfile.write(
                    self._ndjson(
                        {
                            "type": "done",
                            "response": event.response.to_dict(),
                            "billing_status": billing_status,
                        }
                    )
                )
                self.wfile.flush()
                done_seen = True
            if not done_seen:
                raise ConfidentialDataPlaneError("stream ended without final metering evidence")
        except (
            ConfidentialDataPlaneError,
            ConfidentialMeteringError,
            ConfidentialCoordinatorError,
            OSError,
        ):
            # Once headers have been sent, fail closed by terminating the stream.
            # The local proxy withholds OpenAI [DONE] without an authenticated final frame.
            pass
        finally:
            self.close_connection = True

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
        if clean_path in LEGACY_PUBLIC_CONFIDENTIAL_PATHS:
            self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)
            return
        if clean_path == INTERNAL_CONFIDENTIAL_SESSION_PATH:
            self._handle_internal_confidential_session_create()
            return
        if clean_path == INTERNAL_CONFIDENTIAL_COMPLETION_PATH:
            self._handle_internal_confidential_completion()
            return
        if clean_path == INTERNAL_CONFIDENTIAL_STREAM_PATH:
            self._handle_internal_confidential_stream()
            return
        super().do_POST()
