"""Internal encrypted streaming transport for the local OpenAI compatibility proxy."""
from __future__ import annotations

from http import HTTPStatus
import json
from typing import Iterator
from urllib.parse import urlparse

from protocol.confidential_envelope import ConfidentialEnvelope, ConfidentialEnvelopeError
from protocol.confidential_metering import ConfidentialMeteringError
from runtime.confidential.data_plane import ConfidentialDataPlaneError, ConfidentialDataPlaneResult
from runtime.confidential.replay_store import (
    ConfidentialReplayBindingError,
    ConfidentialReplayDetected,
)
from runtime.confidential.session import ConfidentialSessionStateError
from runtime.confidential.stream_data_plane import PinnedHttpsConfidentialStreamDataPlane
from services.gateway.confidential_coordinator import (
    ConfidentialCoordinatorError,
)
from services.gateway.internal_confidential_owner_handler import (
    INTERNAL_CONFIDENTIAL_COMPLETION_PATH,
    INTERNAL_CONFIDENTIAL_SESSION_PATH,
    InternalConfidentialOwnerGatewayHandler,
    LEGACY_PUBLIC_CONFIDENTIAL_PATHS,
)
from services.gateway.live_handler import MAX_CONFIDENTIAL_HTTP_BYTES, LiveGatewayHandler


INTERNAL_CONFIDENTIAL_STREAM_PATH = "/internal/v1/confidential/chat/completions/stream"


class StreamingInternalConfidentialOwnerGatewayHandler(InternalConfidentialOwnerGatewayHandler):
    confidential_stream_data_plane: PinnedHttpsConfidentialStreamDataPlane | None = None

    @staticmethod
    def _ndjson(value: dict) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"

    def _handle_internal_confidential_stream(self) -> None:
        if not self._check_rate_limit():
            return
        auth = self._authenticate_confidential_owner()
        if auth is None:
            return
        coordinator = self.confidential_coordinator
        replay_store = self.confidential_replay_store
        data_plane = self.confidential_stream_data_plane
        if coordinator is None or replay_store is None or data_plane is None:
            self._send_error_response(
                "Confidential streaming execution is not fully configured",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        body = self._read_json_object(max_bytes=MAX_CONFIDENTIAL_HTTP_BYTES)
        if body is None:
            return
        if set(body) != {"computemesh_privacy", "envelope"}:
            self._send_error_response(
                "Invalid protected streaming transport contract",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return
        privacy_value = body.get("computemesh_privacy")
        if privacy_value not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
            self._send_error_response(
                "Invalid confidential privacy class",
                "invalid_request_error",
                HTTPStatus.BAD_REQUEST,
            )
            return
        envelope_value = body.get("envelope")
        if not isinstance(envelope_value, dict):
            self._send_error_response(
                "Confidential envelope is required",
                "invalid_confidential_envelope",
                HTTPStatus.BAD_REQUEST,
            )
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
        session = coordinator.session_store.get(envelope.binding.job_id)
        if session is None or session.account_id != auth.owner_id:
            self._send_error_response("Confidential session not found", "not_found", HTTPStatus.NOT_FOUND)
            return
        if session.state != "OPEN":
            self._send_error_response(
                "Confidential session is not open",
                "confidential_session_state",
                HTTPStatus.CONFLICT,
            )
            return
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
            return

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
            return
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
        except ConfidentialReplayDetected:
            self._send_error_response(
                "Confidential envelope was already consumed",
                "confidential_replay_detected",
                HTTPStatus.CONFLICT,
            )
            return
        except (ConfidentialReplayBindingError, ConfidentialSessionStateError):
            self._send_error_response(
                "Confidential dispatch state is invalid",
                "confidential_session_state",
                HTTPStatus.CONFLICT,
            )
            return
        except Exception:
            self._send_error_response(
                "Confidential replay protection is unavailable",
                "confidential_execution_unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return

        stream: Iterator = iter(data_plane.stream_execute(envelope, endpoint=session.endpoint))
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
            # HTTP/SSE has already started.  Closing without an authenticated final
            # frame makes the local proxy withhold [DONE] and clients see interruption.
            pass
        finally:
            self.close_connection = True

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
        if clean_path in LEGACY_PUBLIC_CONFIDENTIAL_PATHS:
            self._send_error_response("Not Found", "invalid_request_error", HTTPStatus.NOT_FOUND)
            return
        if clean_path == INTERNAL_CONFIDENTIAL_STREAM_PATH:
            self._handle_internal_confidential_stream()
            return
        if clean_path in {INTERNAL_CONFIDENTIAL_SESSION_PATH, INTERNAL_CONFIDENTIAL_COMPLETION_PATH}:
            InternalConfidentialOwnerGatewayHandler.do_POST(self)
            return
        LiveGatewayHandler.do_POST(self)
