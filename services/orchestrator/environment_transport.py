"""Authenticated transport for bounded Mesh environments on NodeOS."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from protocol.node_session import NodeSessionState, SessionSnapshot
from protocol.session_contracts import SessionMessageContractValidator
from services.mcp.platform.environment import (
    EnvironmentKind,
    EnvironmentLease,
    EnvironmentRequest,
    EnvironmentSpec,
)
from services.orchestrator.persistent_control_channel import PersistentNodeControlClient


class EnvironmentTransportError(RuntimeError):
    """Raised when a typed environment request cannot be safely transported."""


class AuthenticatedNodeEnvironmentTransport:
    """Adapt an authenticated NodeOS channel to the bounded environment API."""

    def __init__(
        self,
        control_client: PersistentNodeControlClient,
        *,
        required_capability: str = "mesh_environment_v1",
        timeout_seconds: float = 120.0,
        clock: Any = time.time,
    ) -> None:
        if control_client is None:
            raise ValueError("control_client is required")
        if not 0 < float(timeout_seconds) <= 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        capability = str(required_capability or "").strip()
        if not 1 <= len(capability) <= 128:
            raise ValueError("required_capability is invalid")
        self.control_client = control_client
        self.required_capability = capability
        self.timeout_seconds = float(timeout_seconds)
        self.clock = clock
        self.contracts = SessionMessageContractValidator()
        self._lock = threading.RLock()
        self._lease_nodes: dict[str, str] = {}

    def _session(self, node_id: str) -> SessionSnapshot:
        session = self.control_client.session_for(node_id)
        if session.node_id != node_id or not session.session_id:
            raise EnvironmentTransportError("environment session binding mismatch")
        if session.state is not NodeSessionState.READY:
            raise EnvironmentTransportError("node session is not ready for environments")
        if session.credential_expires_at <= datetime.now(timezone.utc):
            raise EnvironmentTransportError("node session credential has expired")
        if self.required_capability not in {str(value) for value in (session.negotiated_capabilities or ())}:
            raise EnvironmentTransportError("node session lacks mesh environment capability")
        return session

    @staticmethod
    def _spec_payload(spec: EnvironmentSpec) -> dict[str, Any]:
        kind = EnvironmentKind(spec.kind)
        document: dict[str, Any] = {
            "kind": kind.value,
            "allowed_operations": sorted(operation.value for operation in spec.allowed_operations),
            "allowed_paths": list(spec.allowed_paths),
            "network_allowlist": list(spec.network_allowlist),
            "resources": {
                "cpu_millis": spec.resources.cpu_millis,
                "memory_bytes": spec.resources.memory_bytes,
                "vram_bytes": spec.resources.vram_bytes,
                "max_processes": spec.resources.max_processes,
                "max_runtime_seconds": spec.resources.max_runtime_seconds,
            },
            "lease_seconds": spec.lease_seconds,
        }
        if spec.model_id is not None:
            document["model_id"] = spec.model_id
        return document

    def _request(self, *, node_id: str, session: SessionSnapshot, environment_id: str, operation: str,
                 lease_id: str | None = None, lease_revision: int | None = None,
                 request_id: str | None = None, idempotency_key: str | None = None,
                 reason: str | None = None, spec: Mapping[str, Any] | None = None,
                 payload: Mapping[str, Any] | None = None, operation_name: str | None = None) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": 1,
            "session_id": session.session_id,
            "session_revision": session.revision,
            "node_id": node_id,
            "environment_id": environment_id,
            "operation": operation,
        }
        for key, value in (("lease_id", lease_id), ("lease_revision", lease_revision), ("request_id", request_id),
                           ("idempotency_key", idempotency_key), ("reason", reason),
                           ("spec", dict(spec) if spec is not None else None),
                           ("payload", dict(payload) if payload is not None else None), ("operation_name", operation_name)):
            if value is not None:
                document[key] = value
        try:
            self.contracts.validate("EnvironmentRequest", document)
            response = self.control_client.request(node_id=node_id, message_type="EnvironmentRequest",
                                                   payload=document, timeout_seconds=self.timeout_seconds)
            self.contracts.validate("EnvironmentResponse", response)
        except Exception as exc:
            if isinstance(exc, EnvironmentTransportError):
                raise
            raise EnvironmentTransportError("environment transport failed") from exc
        self._validate_response(response, session=session, node_id=node_id, environment_id=environment_id, operation=operation)
        return dict(response)

    @staticmethod
    def _validate_response(response: Mapping[str, Any], *, session: SessionSnapshot, node_id: str,
                           environment_id: str, operation: str) -> None:
        if response.get("session_id") != session.session_id or response.get("session_revision") != session.revision:
            raise EnvironmentTransportError("environment response session binding mismatch")
        if response.get("node_id") != node_id or response.get("environment_id") != environment_id:
            raise EnvironmentTransportError("environment response target binding mismatch")
        if response.get("operation") != operation:
            raise EnvironmentTransportError("environment response operation mismatch")
        if response.get("status") != "ok":
            raise EnvironmentTransportError(str(response.get("reason_code") or "node_rejected_environment_request"))

    def prepare(self, spec: EnvironmentSpec) -> EnvironmentLease:
        if EnvironmentKind(spec.kind) is not EnvironmentKind.MESH or not spec.node_id:
            raise EnvironmentTransportError("authenticated NodeOS transport requires a mesh node")
        node_id = str(spec.node_id)
        response = self._request(node_id=node_id, session=self._session(node_id), environment_id=spec.environment_id,
                                 operation="prepare", spec=self._spec_payload(spec))
        lease = self._lease_from_response(response, environment_id=spec.environment_id)
        with self._lock:
            self._lease_nodes[lease.lease_id] = node_id
        return lease

    def heartbeat(self, lease: EnvironmentLease) -> EnvironmentLease:
        node_id = self._node_for_lease(lease)
        response = self._request(node_id=node_id, session=self._session(node_id), environment_id=lease.environment_id,
                                 operation="heartbeat", lease_id=lease.lease_id, lease_revision=lease.revision)
        renewed = self._lease_from_response(response, environment_id=lease.environment_id)
        if renewed.lease_id != lease.lease_id or renewed.revision <= lease.revision:
            raise EnvironmentTransportError("environment heartbeat did not advance the bound lease")
        return renewed

    def execute(self, lease: EnvironmentLease, request: EnvironmentRequest) -> Mapping[str, Any]:
        node_id = self._node_for_lease(lease)
        response = self._request(node_id=node_id, session=self._session(node_id), environment_id=lease.environment_id,
                                 operation="execute", lease_id=lease.lease_id, lease_revision=lease.revision,
                                 request_id=request.request_id, idempotency_key=request.idempotency_key,
                                 payload=request.payload, operation_name=request.operation.value)
        result = response.get("result", {})
        if not isinstance(result, Mapping):
            raise EnvironmentTransportError("environment response result is not an object")
        return dict(result)

    def shutdown(self, lease: EnvironmentLease, *, reason: str) -> None:
        node_id = self._node_for_lease(lease)
        self._request(node_id=node_id, session=self._session(node_id), environment_id=lease.environment_id,
                      operation="shutdown", lease_id=lease.lease_id, lease_revision=lease.revision, reason=reason)
        with self._lock:
            self._lease_nodes.pop(lease.lease_id, None)

    def _node_for_lease(self, lease: EnvironmentLease) -> str:
        with self._lock:
            node_id = self._lease_nodes.get(lease.lease_id)
        if not node_id:
            raise EnvironmentTransportError("environment lease is unknown to this transport")
        return node_id

    def _lease_from_response(self, response: Mapping[str, Any], *, environment_id: str) -> EnvironmentLease:
        try:
            lease = EnvironmentLease(str(response["lease_id"]), environment_id, float(response["issued_at"]),
                                     float(response["expires_at"]), int(response["lease_revision"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise EnvironmentTransportError("environment response lacks a valid lease") from exc
        lease.validate(now=float(self.clock()), environment_id=environment_id)
        return lease


__all__ = ["AuthenticatedNodeEnvironmentTransport", "EnvironmentTransportError"]
