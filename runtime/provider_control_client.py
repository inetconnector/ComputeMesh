"""Provider-side authenticated persistent control-channel client."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import socket
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.control import CURRENT_PROTOCOL_MINOR, SUPPORTED_PROTOCOL_MAJOR, ControlEnvelope
from protocol.node_identity import AUTH_METHOD, create_node_auth_proof
from protocol.node_session import NodeHelloInfo, NodeSessionState, SessionSnapshot
from services.orchestrator.persistent_control_channel import recv_frame, send_frame


class ProviderHandshakeError(RuntimeError):
    pass


def _envelope(*, message_type: str, actor_id: str, target_id: str, revision: int, payload: dict[str, Any]) -> ControlEnvelope:
    now = datetime.now(timezone.utc)
    return ControlEnvelope(
        protocol_major=SUPPORTED_PROTOCOL_MAJOR,
        protocol_minor=CURRENT_PROTOCOL_MINOR,
        message_type=message_type,
        request_id=f"provider-{message_type.lower()}-{now.timestamp():.6f}",
        correlation_id="provider-session-handshake",
        actor_id=actor_id,
        target_id=target_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        expected_revision=revision,
        payload=payload,
    )


def perform_provider_handshake(
    *,
    sock: socket.socket,
    challenge_frame: dict[str, Any],
    node_id: str,
    key_id: str,
    private_key: Ed25519PrivateKey,
    agent_version: str,
    platform: str,
    capabilities: tuple[str, ...] = ("execution_attestation_v1",),
) -> SessionSnapshot:
    session_id = challenge_frame.get("session_id")
    challenge = challenge_frame.get("challenge")
    control_plane_id = challenge_frame.get("control_plane_id")
    if not all(isinstance(v, str) and v for v in (session_id, challenge, control_plane_id)):
        raise ProviderHandshakeError("invalid control-plane challenge")
    hello = NodeHelloInfo(
        agent_version=agent_version,
        platform=platform,
        supported_auth_methods=(AUTH_METHOD,),
        capabilities=frozenset(capabilities),
        node_id=node_id,
        protocol_major=SUPPORTED_PROTOCOL_MAJOR,
        protocol_minor=CURRENT_PROTOCOL_MINOR,
    )
    hello_payload = {
        "protocol_major": hello.protocol_major,
        "protocol_minor": hello.protocol_minor,
        "agent_version": hello.agent_version,
        "platform": hello.platform,
        "node_id": node_id,
        "supported_auth_methods": list(hello.supported_auth_methods),
        "capabilities": sorted(hello.capabilities),
    }
    send_frame(sock, {"kind": "envelope", "document": _envelope(message_type="NodeHello", actor_id=node_id, target_id=control_plane_id, revision=0, payload=hello_payload).to_dict()})
    ack = recv_frame(sock)
    if ack.get("kind") != "session_ack" or ack.get("revision") != 1:
        raise ProviderHandshakeError("NodeHello was not accepted")

    credential = create_node_auth_proof(
        private_key=private_key,
        node_id=node_id,
        key_id=key_id,
        session_id=session_id,
        challenge=challenge,
        hello=hello,
    )
    send_frame(sock, {"kind": "envelope", "document": _envelope(message_type="NodeAuthenticate", actor_id=node_id, target_id=control_plane_id, revision=1, payload={"method": AUTH_METHOD, "credential": credential}).to_dict()})
    ack = recv_frame(sock)
    if ack.get("kind") != "session_ack" or ack.get("revision") != 2:
        raise ProviderHandshakeError("NodeAuthenticate was not accepted")

    send_frame(sock, {"kind": "envelope", "document": _envelope(message_type="CapabilityNegotiation", actor_id=node_id, target_id=control_plane_id, revision=2, payload={"accepted_capabilities": sorted(capabilities)}).to_dict()})
    ack = recv_frame(sock)
    if ack.get("kind") != "session_ack" or ack.get("revision") != 3:
        raise ProviderHandshakeError("CapabilityNegotiation was not accepted")
    return SessionSnapshot(
        session_id=session_id,
        state=NodeSessionState.CAPABILITIES_NEGOTIATED,
        revision=3,
        protocol_major=SUPPORTED_PROTOCOL_MAJOR,
        protocol_minor=CURRENT_PROTOCOL_MINOR,
        node_id=node_id,
        principal_id=node_id,
        auth_method=AUTH_METHOD,
        credential_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        negotiated_capabilities=frozenset(capabilities),
        profile_revision=None,
        drain_reason=None,
        close_reason=None,
    )


def make_handshake(*, node_id: str, key_id: str, private_key: Ed25519PrivateKey, agent_version: str, platform: str, capabilities: tuple[str, ...] = ("execution_attestation_v1",)) -> Callable[[socket.socket, dict[str, Any]], SessionSnapshot]:
    def handshake(sock: socket.socket, challenge: dict[str, Any]) -> SessionSnapshot:
        return perform_provider_handshake(
            sock=sock,
            challenge_frame=challenge,
            node_id=node_id,
            key_id=key_id,
            private_key=private_key,
            agent_version=agent_version,
            platform=platform,
            capabilities=capabilities,
        )
    return handshake
