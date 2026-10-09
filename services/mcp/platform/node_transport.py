"""Bridge authenticated NodeOS session snapshots into the public node registry."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from .node_registry import NodeLifecycle, NodeRecord, NodeRegistry


class AuthenticatedNodeSyncError(RuntimeError):
    """Raised when a node cannot be admitted from an authenticated session."""


@dataclass(frozen=True)
class NodeSyncResult:
    node: NodeRecord
    session_id: str
    profile_revision: int
    refreshed: bool


_READY_SESSION_STATES = {"capabilities_negotiated", "profile_synced", "ready"}
_MODEL_KEYS = {
    "id", "model", "name", "model_id", "available", "status", "capabilities",
    "modalities", "quantization", "size_bytes", "parameters", "slots",
    "free_vram_bytes", "available_vram_bytes", "vram_bytes", "context_tokens",
    "context_size", "max_context_tokens", "throughput_tokens_per_second",
}


def _state_value(value: Any) -> str:
    return str(getattr(value, "value", value)).strip().lower()


def _sanitize_models(models: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    if len(models) > 512:
        raise AuthenticatedNodeSyncError("node model catalogue is too large")
    sanitized: list[dict[str, Any]] = []
    for raw in models:
        if not isinstance(raw, Mapping):
            raise AuthenticatedNodeSyncError("node model catalogue contains a non-object")
        item: dict[str, Any] = {}
        for key in _MODEL_KEYS:
            if key not in raw:
                continue
            value = raw[key]
            if key in {"capabilities", "modalities"}:
                if not isinstance(value, (list, tuple, set)):
                    continue
                item[key] = [str(entry)[:128] for entry in list(value)[:32]]
            elif isinstance(value, (str, int, float, bool)) or value is None:
                item[key] = value
        identifier = item.get("id") or item.get("model") or item.get("name") or item.get("model_id")
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 256:
            raise AuthenticatedNodeSyncError("node model catalogue contains an invalid model identifier")
        sanitized.append(item)
    return tuple(sanitized)


class AuthenticatedNodeRegistrySync:
    """Admit only live, authenticated, non-expired NodeSession snapshots."""

    def __init__(
        self,
        registry: NodeRegistry,
        *,
        clock: Callable[[], datetime] | None = None,
        required_capability: str = "execution_attestation_v1",
        control_client: Any | None = None,
    ) -> None:
        self.registry = registry
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.required_capability = str(required_capability)
        self.control_client = control_client

    def _validate_session(self, session: Any, node_id: str) -> tuple[str, str, str, int]:
        session_node = str(getattr(session, "node_id", "") or "")
        if session_node != str(node_id):
            raise AuthenticatedNodeSyncError("authenticated session identity does not match node")
        principal_id = str(getattr(session, "principal_id", "") or "")
        key_id = str(getattr(session, "key_id", "") or "")
        session_id = str(getattr(session, "session_id", "") or "")
        if not principal_id or not key_id or not session_id:
            raise AuthenticatedNodeSyncError("authenticated session lacks identity binding")
        if _state_value(getattr(session, "state", "")) not in _READY_SESSION_STATES:
            raise AuthenticatedNodeSyncError("node session is not ready for agent execution")
        expires = getattr(session, "credential_expires_at", None)
        if expires is None:
            raise AuthenticatedNodeSyncError("node session has no credential expiry")
        expires = expires.astimezone(timezone.utc) if getattr(expires, "tzinfo", None) else None
        if expires is None or expires <= self.clock().astimezone(timezone.utc):
            raise AuthenticatedNodeSyncError("node session credential has expired")
        capabilities = {str(item) for item in (getattr(session, "negotiated_capabilities", ()) or ())}
        if self.required_capability and self.required_capability not in capabilities:
            raise AuthenticatedNodeSyncError(f"node session lacks {self.required_capability}")
        if self.control_client is not None:
            connected = getattr(self.control_client, "is_connected", None)
            if not callable(connected) or not bool(connected(node_id)):
                raise AuthenticatedNodeSyncError("authenticated node has no live persistent control channel")
        revision = getattr(session, "profile_revision", None)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise AuthenticatedNodeSyncError("node session has no valid profile revision")
        return session_id, principal_id, key_id, revision

    def sync(
        self,
        *,
        node_id: str,
        endpoint: str,
        session: Any,
        profile: Mapping[str, Any],
        models: Sequence[Mapping[str, Any]],
        benchmark: Mapping[str, Any] | None = None,
    ) -> NodeSyncResult:
        session_id, principal_id, key_id, profile_revision = self._validate_session(session, node_id)
        try:
            profile_revision_value = int(profile.get("profile_revision", -1))
        except (TypeError, ValueError):
            raise AuthenticatedNodeSyncError("node profile has no valid profile revision") from None
        if str(profile.get("node_id")) != str(node_id) or profile_revision_value != profile_revision:
            raise AuthenticatedNodeSyncError("node profile is not bound to the authenticated session revision")
        sanitized_models = _sanitize_models(models)
        capabilities_set = {str(item) for item in (getattr(session, "negotiated_capabilities", ()) or ())}
        for key in ("capabilities", "agent_capabilities"):
            raw_capabilities = profile.get(key, ())
            if isinstance(raw_capabilities, (list, tuple, set)):
                capabilities_set.update(str(item) for item in raw_capabilities if str(item))
        capabilities = tuple(sorted(capabilities_set))
        evidence = hashlib.sha256(
            json.dumps({"node_id": node_id, "session_id": session_id, "principal_id": principal_id, "profile_revision": profile_revision, "key_id": key_id}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        try:
            current = self.registry.get(node_id)
        except KeyError:
            current = None
        if current is not None and current.status is NodeLifecycle.REVOKED:
            raise AuthenticatedNodeSyncError("revoked node cannot be re-admitted")
        if current is not None and current.identity_key_id and current.identity_key_id != key_id:
            raise AuthenticatedNodeSyncError("node identity key changed for an existing registry entry")
        if current is not None and current.principal_id and current.principal_id != principal_id:
            raise AuthenticatedNodeSyncError("node principal changed for an existing registry entry")
        existed = current is not None
        if current is None:
            self.registry.discover(node_id, endpoint, discovery_source="authenticated_session")
            current = self.registry.get(node_id)
        elif current.status in {NodeLifecycle.QUARANTINED, NodeLifecycle.FAILED}:
            self.registry.mark_reachable(node_id)
            current = self.registry.get(node_id)
        if current.status is NodeLifecycle.DISCOVERED:
            self.registry.mark_reachable(node_id)
            current = self.registry.get(node_id)
        if current.status is NodeLifecycle.REACHABLE:
            self.registry.record_capabilities(node_id, capabilities=capabilities, models=sanitized_models, profile_revision=profile_revision)
            current = self.registry.get(node_id)
        else:
            self.registry.refresh_verified_capabilities(node_id, capabilities=capabilities, models=sanitized_models, profile_revision=profile_revision)
            current = self.registry.get(node_id)
        if current.status is NodeLifecycle.CAPABILITY_PROBED:
            self.registry.verify_identity(node_id, identity_key_id=key_id, evidence_digest=evidence)
            current = self.registry.get(node_id)
        if current.status is NodeLifecycle.IDENTITY_VERIFIED:
            self.registry.mark_authenticated(node_id, principal_id=principal_id)
            current = self.registry.get(node_id)
        if current.status is NodeLifecycle.AUTHENTICATED:
            self.registry.mark_prepared(node_id, preparation_digest=evidence)
            current = self.registry.get(node_id)
        if current.status is NodeLifecycle.PREPARED:
            self.registry.record_benchmark(node_id, accepted=True, metrics=dict(benchmark or {"source": "authenticated_session", "profile_revision": profile_revision}))
            current = self.registry.get(node_id)
        if current.status not in {NodeLifecycle.READY, NodeLifecycle.ACTIVE}:
            raise AuthenticatedNodeSyncError(f"node did not reach a routable state: {current.status.value}")
        return NodeSyncResult(current, session_id, profile_revision, existed)
