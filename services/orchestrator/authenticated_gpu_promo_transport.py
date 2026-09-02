"""Session-authenticated transport for GPU onboarding challenges.

GPU promo work is sent only across an existing Ed25519-authenticated persistent
provider session. The transport records wall-clock round-trip duration on the
control-plane side; provider-reported elapsed time is never treated as sufficient
proof by itself. The enrolled key id is retained by the authenticated session and
is the authoritative key binding for GPU promo challenges.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from protocol.node_session import NodeSessionState, SessionSnapshot
from protocol.session_contracts import SessionMessageContractValidator
from runtime.llama.gpu_promo_challenge import GPU_PROMO_CAPABILITY
from services.orchestrator.authenticated_attestation_transport import NodeControlClient


class AuthenticatedGpuPromoTransportError(RuntimeError):
    pass


class NodeSessionRegistry(Protocol):
    def get_session(self, node_id: str) -> SessionSnapshot: ...


@dataclass(frozen=True)
class GpuPromoTransportResult:
    proof: dict[str, Any]
    server_roundtrip_ms: float
    session_id: str
    session_revision: int


@dataclass
class SessionAuthenticatedGpuPromoTransport:
    sessions: NodeSessionRegistry
    client: NodeControlClient

    def _require_authenticated_session(self, node_id: str) -> SessionSnapshot:
        try:
            session = self.sessions.get_session(node_id)
        except KeyError as exc:
            raise AuthenticatedGpuPromoTransportError(
                f"node {node_id} has no authenticated control-plane session"
            ) from exc
        if session.node_id != node_id:
            raise AuthenticatedGpuPromoTransportError("session identity does not match target node")
        if session.state not in {
            NodeSessionState.CAPABILITIES_NEGOTIATED,
            NodeSessionState.PROFILE_SYNCED,
            NodeSessionState.READY,
        }:
            raise AuthenticatedGpuPromoTransportError(
                f"node {node_id} session is not authorized for GPU promo work"
            )
        if (
            session.credential_expires_at is None
            or session.credential_expires_at <= datetime.now(timezone.utc)
        ):
            raise AuthenticatedGpuPromoTransportError(f"node {node_id} authentication has expired")
        if not session.key_id:
            raise AuthenticatedGpuPromoTransportError(
                f"node {node_id} authenticated session has no enrolled key binding"
            )
        if GPU_PROMO_CAPABILITY not in session.negotiated_capabilities:
            raise AuthenticatedGpuPromoTransportError(
                f"node {node_id} did not negotiate {GPU_PROMO_CAPABILITY}"
            )
        if not self.client.is_connected(node_id):
            raise AuthenticatedGpuPromoTransportError(
                f"node {node_id} has no live persistent control channel"
            )
        return session

    def authenticated_key_id(self, node_id: str) -> str:
        """Return only the key id proven by the live authenticated provider session."""
        session = self._require_authenticated_session(node_id)
        assert session.key_id is not None
        return session.key_id

    def request_gpu_promo_challenge(
        self,
        *,
        node_id: str,
        challenge_document: dict[str, Any],
        timeout_seconds: float,
    ) -> GpuPromoTransportResult:
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        if not isinstance(challenge_document, dict):
            raise AuthenticatedGpuPromoTransportError("GPU promo challenge must be an object")

        session = self._require_authenticated_session(node_id)
        if challenge_document.get("node_id") != node_id:
            raise AuthenticatedGpuPromoTransportError("GPU promo challenge targets another node")
        if challenge_document.get("key_id") != session.key_id:
            raise AuthenticatedGpuPromoTransportError(
                "GPU promo challenge key does not match authenticated session key"
            )

        payload = {
            "session_id": session.session_id,
            "session_revision": session.revision,
            "challenge": dict(challenge_document),
        }
        contracts = SessionMessageContractValidator()
        contracts.validate("GpuPromoChallengeRequest", payload)

        started = time.monotonic()
        response = self.client.request(
            node_id=node_id,
            message_type="GpuPromoChallengeRequest",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        server_roundtrip_ms = (time.monotonic() - started) * 1000.0
        if not isinstance(response, dict):
            raise AuthenticatedGpuPromoTransportError("node returned a non-object GPU promo response")
        contracts.validate("GpuPromoChallengeResponse", response)

        if response.get("session_id") != session.session_id:
            raise AuthenticatedGpuPromoTransportError("GPU promo response is bound to another session")
        if response.get("session_revision") != session.revision:
            raise AuthenticatedGpuPromoTransportError("GPU promo response session revision mismatch")
        if response.get("node_id") != node_id:
            raise AuthenticatedGpuPromoTransportError("GPU promo response node identity mismatch")
        if response.get("key_id") != session.key_id:
            raise AuthenticatedGpuPromoTransportError("GPU promo response key binding mismatch")

        proof = response.get("proof")
        assert isinstance(proof, dict)
        if proof.get("node_id") != node_id:
            raise AuthenticatedGpuPromoTransportError("GPU promo proof node identity mismatch")
        if proof.get("challenge_id") != challenge_document.get("challenge_id"):
            raise AuthenticatedGpuPromoTransportError("GPU promo proof challenge id mismatch")
        if proof.get("key_id") != session.key_id:
            raise AuthenticatedGpuPromoTransportError("GPU promo proof key id mismatch")

        return GpuPromoTransportResult(
            proof=dict(proof),
            server_roundtrip_ms=server_roundtrip_ms,
            session_id=session.session_id,
            session_revision=session.revision,
        )
