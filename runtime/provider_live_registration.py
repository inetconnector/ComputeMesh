"""Publish provider scheduling inputs over an authenticated persistent control channel."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Iterable

from protocol.control import ControlEnvelope
from protocol.node_session import SessionSnapshot
from services.orchestrator.persistent_control_channel import recv_frame, send_frame


class ProviderRegistrationError(RuntimeError):
    pass


def _push_envelope(*, session: SessionSnapshot, control_plane_id: str, message_type: str, payload: dict[str, Any]) -> ControlEnvelope:
    if not session.node_id or session.protocol_major is None or session.protocol_minor is None:
        raise ProviderRegistrationError("provider session is not authenticated/negotiated")
    now = datetime.now(timezone.utc)
    return ControlEnvelope(
        protocol_major=session.protocol_major,
        protocol_minor=session.protocol_minor,
        message_type=message_type,
        request_id=f"provider-push-{secrets.token_hex(12)}",
        correlation_id=session.session_id,
        actor_id=session.node_id,
        target_id=control_plane_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        expected_revision=session.revision,
        payload=payload,
    )


def push_and_ack(sock: Any, *, session: SessionSnapshot, control_plane_id: str, message_type: str, payload: dict[str, Any]) -> SessionSnapshot:
    envelope = _push_envelope(
        session=session,
        control_plane_id=control_plane_id,
        message_type=message_type,
        payload=payload,
    )
    send_frame(sock, {"kind": "envelope", "document": envelope.to_dict()})
    ack = recv_frame(sock)
    if ack.get("kind") != "session_ack" or not isinstance(ack.get("revision"), int):
        raise ProviderRegistrationError(f"{message_type} was not acknowledged")
    revision = int(ack["revision"])
    state_name = ack.get("state")
    try:
        state = type(session.state)(state_name)
    except Exception as exc:
        raise ProviderRegistrationError("control plane returned invalid session state") from exc
    return SessionSnapshot(
        session_id=session.session_id,
        state=state,
        revision=revision,
        protocol_major=session.protocol_major,
        protocol_minor=session.protocol_minor,
        node_id=session.node_id,
        principal_id=session.principal_id,
        auth_method=session.auth_method,
        credential_expires_at=session.credential_expires_at,
        negotiated_capabilities=session.negotiated_capabilities,
        profile_revision=(int(payload["profile_revision"]) if message_type == "NodeProfileUpdate" else session.profile_revision),
        drain_reason=(str(payload.get("reason")) if message_type == "DrainRequest" else session.drain_reason),
        close_reason=session.close_reason,
    )


def publish_live_registration(
    sock: Any,
    *,
    session: SessionSnapshot,
    control_plane_id: str,
    profile: dict[str, Any],
    llama_build_commit: str,
    llama_build_number: int,
    rpc_host: str,
    rpc_port: int,
    benchmarks: Iterable[dict[str, Any]],
) -> SessionSnapshot:
    """Push profile, runtime/RPC advertisement and current scheduler benchmarks in order."""
    current = push_and_ack(
        sock,
        session=session,
        control_plane_id=control_plane_id,
        message_type="NodeProfileUpdate",
        payload=dict(profile),
    )
    runtime = {
        "schema_version": 1,
        "node_id": current.node_id,
        "profile_revision": current.profile_revision,
        "runtime": "llama.cpp",
        "llama_build_commit": llama_build_commit,
        "llama_build_number": llama_build_number,
        "rpc": {"host": rpc_host, "port": rpc_port},
    }
    current = push_and_ack(
        sock,
        session=current,
        control_plane_id=control_plane_id,
        message_type="RuntimeAdvertisement",
        payload=runtime,
    )
    for benchmark in benchmarks:
        current = push_and_ack(
            sock,
            session=current,
            control_plane_id=control_plane_id,
            message_type="BenchmarkReport",
            payload=dict(benchmark),
        )
    return current
