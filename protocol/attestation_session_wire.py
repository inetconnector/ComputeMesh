"""Bind execution-attestation request/response messages to an authenticated NodeSession."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Any

from .control import ControlEnvelope
from .node_session import NodeSessionState, SessionSnapshot
from .session_contracts import SessionMessageContractValidator

ATTESTATION_CAPABILITY = "execution_attestation_v1"


class AttestationSessionWireError(RuntimeError):
    pass


def _require_live_attestation_session(session: SessionSnapshot, *, now: datetime | None = None) -> None:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if session.state not in {
        NodeSessionState.CAPABILITIES_NEGOTIATED,
        NodeSessionState.PROFILE_SYNCED,
        NodeSessionState.READY,
    }:
        raise AttestationSessionWireError("node session is not ready for attestation traffic")
    if not session.node_id:
        raise AttestationSessionWireError("node session has no authenticated node identity")
    if session.credential_expires_at is None or session.credential_expires_at <= current:
        raise AttestationSessionWireError("node session authentication has expired")
    if ATTESTATION_CAPABILITY not in session.negotiated_capabilities:
        raise AttestationSessionWireError("node session did not negotiate execution attestation capability")


def build_attestation_request_envelope(
    *,
    session: SessionSnapshot,
    control_plane_id: str,
    request_document: dict[str, Any],
    now: datetime | None = None,
    ttl: timedelta = timedelta(seconds=30),
) -> ControlEnvelope:
    _require_live_attestation_session(session, now=now)
    if not control_plane_id or len(control_plane_id) > 256:
        raise ValueError("invalid control_plane_id")
    if ttl <= timedelta(0) or ttl > timedelta(minutes=2):
        raise ValueError("attestation request ttl must be within (0, 2 minutes]")
    if session.protocol_major is None or session.protocol_minor is None:
        raise AttestationSessionWireError("node session protocol is not negotiated")
    payload = {
        "session_id": session.session_id,
        "session_revision": session.revision,
        "request": dict(request_document),
    }
    SessionMessageContractValidator().validate("ExecutionAttestationRequest", payload)
    issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    request_id = str(request_document["request_id"])
    return ControlEnvelope(
        protocol_major=session.protocol_major,
        protocol_minor=session.protocol_minor,
        message_type="ExecutionAttestationRequest",
        request_id=f"wire-{secrets.token_hex(12)}",
        correlation_id=request_id,
        actor_id=control_plane_id,
        target_id=session.node_id,
        issued_at=issued,
        expires_at=issued + ttl,
        expected_revision=session.revision,
        payload=payload,
    )


def validate_attestation_response_envelope(
    envelope: ControlEnvelope,
    *,
    session: SessionSnapshot,
    expected_request_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_live_attestation_session(session, now=now)
    if envelope.message_type != "ExecutionAttestationResponse":
        raise AttestationSessionWireError("unexpected control message type")
    SessionMessageContractValidator().validate(envelope.message_type, envelope.payload)
    if session.protocol_major != envelope.protocol_major or session.protocol_minor != envelope.protocol_minor:
        raise AttestationSessionWireError("attestation response protocol does not match node session")
    if envelope.actor_id != session.node_id:
        raise AttestationSessionWireError("attestation response actor is not the authenticated node")
    if envelope.target_id == session.node_id:
        raise AttestationSessionWireError("attestation response target cannot be the sending node")
    if envelope.expected_revision != session.revision:
        raise AttestationSessionWireError("attestation response session revision mismatch")
    payload = dict(envelope.payload)
    if payload["session_id"] != session.session_id:
        raise AttestationSessionWireError("attestation response session ID mismatch")
    if payload["node_id"] != session.node_id:
        raise AttestationSessionWireError("attestation response node ID mismatch")
    if payload["request_id"] != expected_request_id or envelope.correlation_id != expected_request_id:
        raise AttestationSessionWireError("attestation response correlation mismatch")
    attestation = payload["attestation"]
    if attestation["node_id"] != session.node_id:
        raise AttestationSessionWireError("attestation claims another node identity")
    return dict(attestation)
