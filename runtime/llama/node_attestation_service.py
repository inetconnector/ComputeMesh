"""Node-local handler for authenticated execution-attestation requests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization

from protocol.node_identity import key_id_from_public_key
from runtime.llama.job_attestation import JobAttestationError, _canonical_sha256, _load_private_key
from services.gateway.execution_attestation import AttestationClaims, create_execution_attestation


class NodeAttestationServiceError(RuntimeError):
    pass


class NodeAttestationService:
    """Sign only requests addressed to this node and bound to its live session."""

    def __init__(self, *, node_id: str, private_key_path: Path) -> None:
        if not node_id or len(node_id) > 128:
            raise ValueError("invalid node_id")
        self.node_id = node_id
        self.private_key_path = private_key_path

    def handle(
        self,
        *,
        authenticated_node_id: str,
        session_id: str,
        request_session_id: str,
        request_document: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if authenticated_node_id != self.node_id:
            raise NodeAttestationServiceError("authenticated session is not bound to this node")
        if request_session_id != session_id:
            raise NodeAttestationServiceError("attestation request session binding mismatch")
        required = {
            "schema_version", "request_id", "job_id", "placement_decision_id", "model_sha256",
            "runtime_sha256", "evidence_sha256", "output_sha256", "expected_nodes",
        }
        if not isinstance(request_document, dict) or set(request_document) != required:
            raise NodeAttestationServiceError("invalid execution-attestation request")
        if request_document.get("schema_version") != 1:
            raise NodeAttestationServiceError("unsupported execution-attestation request version")
        unsigned = {k: v for k, v in request_document.items() if k != "request_id"}
        expected_request_id = "execution-attestation-request-" + _canonical_sha256(unsigned)[:16]
        if request_document.get("request_id") != expected_request_id:
            raise NodeAttestationServiceError("attestation request claims were modified")
        nodes = request_document.get("expected_nodes")
        if not isinstance(nodes, list) or self.node_id not in nodes or len(nodes) < 2 or len(set(nodes)) != len(nodes):
            raise NodeAttestationServiceError("node is not a valid selected participant")
        try:
            private_key = _load_private_key(self.private_key_path)
        except JobAttestationError as exc:
            raise NodeAttestationServiceError("node signing key is unavailable") from exc
        public_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        claims = AttestationClaims(
            node_id=self.node_id,
            key_id=key_id_from_public_key(public_raw),
            job_id=request_document["job_id"],
            placement_decision_id=request_document["placement_decision_id"],
            model_sha256=request_document["model_sha256"],
            runtime_sha256=request_document["runtime_sha256"],
            evidence_sha256=request_document["evidence_sha256"],
            output_sha256=request_document["output_sha256"],
            issued_at=int(issued.timestamp()),
            expires_at=int((issued + timedelta(minutes=2)).timestamp()),
        )
        return {
            "session_id": session_id,
            "node_id": self.node_id,
            "attestation": create_execution_attestation(private_key=private_key, claims=claims),
        }
