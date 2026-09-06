"""Session-authenticated transport adapter for execution-attestation collection.

The underlying network client may use TLS/mesh tunnels, but authorization is bound
to the existing ComputeMesh Ed25519-authenticated NodeSession. TLS certificates are
not treated as node identity unless a future PKI explicitly makes them so.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from protocol.node_session import NodeSessionState, SessionSnapshot
from services.orchestrator.attestation_collection import NodeAttestationTransport

ATTESTATION_CAPABILITY = "execution_attestation_v1"
CAPACITY_RESERVATION_CAPABILITY = "capacity_reservation_v1"


class AuthenticatedAttestationTransportError(RuntimeError):
    pass


class NodeSessionRegistry(Protocol):
    def get_session(self, node_id: str) -> SessionSnapshot: ...


class NodeControlClient(Protocol):
    def is_connected(self, node_id: str) -> bool: ...

    def request(
        self,
        *,
        node_id: str,
        message_type: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


@dataclass
class SessionAuthenticatedAttestationTransport(NodeAttestationTransport):
    sessions: NodeSessionRegistry
    client: NodeControlClient

    def _require_authenticated_session(self, node_id: str) -> SessionSnapshot:
        try:
            session = self.sessions.get_session(node_id)
        except KeyError as exc:
            raise AuthenticatedAttestationTransportError(
                f"node {node_id} has no authenticated control-plane session"
            ) from exc
        if session.node_id != node_id:
            raise AuthenticatedAttestationTransportError("session identity does not match target node")
        if session.state not in {
            NodeSessionState.CAPABILITIES_NEGOTIATED,
            NodeSessionState.PROFILE_SYNCED,
            NodeSessionState.READY,
        }:
            raise AuthenticatedAttestationTransportError(
                f"node {node_id} session is not authorized for control-plane requests"
            )
        if session.credential_expires_at is None or session.credential_expires_at <= datetime.now(timezone.utc):
            raise AuthenticatedAttestationTransportError(f"node {node_id} authentication has expired")
        if ATTESTATION_CAPABILITY not in session.negotiated_capabilities:
            raise AuthenticatedAttestationTransportError(
                f"node {node_id} did not negotiate {ATTESTATION_CAPABILITY}"
            )
        if not self.client.is_connected(node_id):
            raise AuthenticatedAttestationTransportError(
                f"node {node_id} has no live persistent control channel"
            )
        return session

    def request_execution_attestation(
        self,
        *,
        node_id: str,
        request_document: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        session = self._require_authenticated_session(node_id)
        if node_id not in request_document.get("expected_nodes", []):
            raise AuthenticatedAttestationTransportError("target node is not part of attestation request")
        response = self.client.request(
            node_id=node_id,
            message_type="ExecutionAttestationRequest",
            payload={
                "session_id": session.session_id,
                "session_revision": session.revision,
                "request": dict(request_document),
            },
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(response, dict):
            raise AuthenticatedAttestationTransportError("node returned a non-object response")
        if response.get("session_id") != session.session_id:
            raise AuthenticatedAttestationTransportError("node response is bound to another session")
        if response.get("node_id") != node_id:
            raise AuthenticatedAttestationTransportError("node response identity mismatch")
        attestation = response.get("attestation")
        if not isinstance(attestation, dict):
            raise AuthenticatedAttestationTransportError("node response lacks an attestation")
        return attestation

    def _require_capacity_session(self, node_id: str) -> SessionSnapshot:
        session = self._require_authenticated_session(node_id)
        if CAPACITY_RESERVATION_CAPABILITY not in session.negotiated_capabilities:
            raise AuthenticatedAttestationTransportError(
                f"node {node_id} did not negotiate {CAPACITY_RESERVATION_CAPABILITY}"
            )
        return session

    def reserve_capacity(self, *, node_id: str, job_id: str, lease_id: str, ttl_seconds: int, device_id: str = "default", memory_mb: int = 0, timeout_seconds: float = 15.0) -> dict[str, Any]:
        session = self._require_capacity_session(node_id)
        response = self.client.request(
            node_id=node_id,
            message_type="CapacityReserveRequest",
            payload={"job_id": job_id, "lease_id": lease_id, "ttl_seconds": ttl_seconds, "device_id": device_id, "memory_mb": memory_mb},
            timeout_seconds=timeout_seconds,
        )
        if response.get("node_id") != node_id or response.get("job_id") != job_id or response.get("lease_id") != lease_id:
            raise AuthenticatedAttestationTransportError("provider capacity reservation binding mismatch")
        return response

    def release_capacity(self, *, node_id: str, job_id: str, lease_id: str, timeout_seconds: float = 15.0) -> bool:
        session = self._require_capacity_session(node_id)
        response = self.client.request(
            node_id=node_id,
            message_type="CapacityReleaseRequest",
            payload={"job_id": job_id, "lease_id": lease_id},
            timeout_seconds=timeout_seconds,
        )
        if response.get("node_id") != node_id or response.get("job_id") != job_id:
            raise AuthenticatedAttestationTransportError("provider capacity release binding mismatch")
        return bool(response.get("released", False))
