# SPDX-License-Identifier: Apache-2.0
"""Lease-independent, authorization-gated model preparation contracts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .node_registry import NodeLifecycle, NodeRecord, NodeRegistry


class ModelPreparationError(RuntimeError):
    """Raised when a preparation request or transport response is invalid."""


@dataclass(frozen=True)
class ModelArtifactSpec:
    model_id: str
    artifact_digest: str
    size_bytes: int
    capabilities: tuple[str, ...] = ()
    context_tokens: int = 0
    source: str = "verified_catalog"

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:/@+-]{1,256}", self.model_id):
            raise ModelPreparationError("invalid model_id")
        if not re.fullmatch(r"(?:sha256:)?[A-Fa-f0-9]{64}", self.artifact_digest):
            raise ModelPreparationError("artifact_digest must be a SHA-256 digest")
        if int(self.size_bytes) < 1 or int(self.size_bytes) > 8 * 1024**4:
            raise ModelPreparationError("model artifact size is outside the supported bound")
        if int(self.context_tokens) < 0 or int(self.context_tokens) > 2**31 - 1:
            raise ModelPreparationError("context_tokens is outside the supported bound")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "model_id": self.model_id,
            "artifact_digest": self.artifact_digest.lower(),
            "size_bytes": int(self.size_bytes),
            "capabilities": list(self.capabilities),
            "context_tokens": int(self.context_tokens),
            "source": self.source,
        }


@dataclass(frozen=True)
class ModelPreparationPlan:
    node_id: str
    model: ModelArtifactSpec
    status: str
    reason_code: str
    idempotency_key: str
    node_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "model": self.model.to_dict(),
            "status": self.status,
            "reason_code": self.reason_code,
            "idempotency_key": self.idempotency_key,
            "node_status": self.node_status,
        }


@dataclass(frozen=True)
class ModelPreparationResult:
    plan: ModelPreparationPlan
    response: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"plan": self.plan.to_dict(), "response": dict(self.response)}


ModelPreparationTransport = Callable[[NodeRecord, Mapping[str, Any]], Mapping[str, Any]]


class ModelPreparationCoordinator:
    """Plan and optionally execute one exact model preparation operation."""

    def __init__(self, registry: NodeRegistry, transport: ModelPreparationTransport | None = None) -> None:
        self.registry = registry
        self.transport = transport

    @staticmethod
    def _has_model(node: NodeRecord, model: ModelArtifactSpec) -> bool:
        expected = model.artifact_digest.lower().removeprefix("sha256:")
        for record in node.models:
            if not isinstance(record, Mapping):
                continue
            model_id = record.get("model_id") or record.get("id") or record.get("name")
            digest = str(record.get("artifact_digest") or record.get("digest") or "").lower().removeprefix("sha256:")
            if str(model_id) == model.model_id and (not expected or digest == expected):
                return True
        return False

    @staticmethod
    def _key(node_id: str, model: ModelArtifactSpec) -> str:
        raw = f"{node_id}\0{model.model_id}\0{model.artifact_digest.lower()}".encode("utf-8")
        return f"modelprep_{hashlib.sha256(raw).hexdigest()}"

    def plan(self, node_id: str, model: ModelArtifactSpec) -> ModelPreparationPlan:
        model.validate()
        node = self.registry.get(node_id)
        key = self._key(node.node_id, model)
        if node.status in {NodeLifecycle.DISCOVERED, NodeLifecycle.REACHABLE, NodeLifecycle.CAPABILITY_PROBED, NodeLifecycle.IDENTITY_VERIFIED}:
            return ModelPreparationPlan(node.node_id, model, "manual_action_required", "authentication_required", key, node.status.value)
        if node.status in {NodeLifecycle.QUARANTINED, NodeLifecycle.FAILED, NodeLifecycle.REVOKED, NodeLifecycle.DRAINING}:
            return ModelPreparationPlan(node.node_id, model, "blocked", "node_not_ready", key, node.status.value)
        if self._has_model(node, model):
            return ModelPreparationPlan(node.node_id, model, "available", "model_already_advertised", key, node.status.value)
        return ModelPreparationPlan(node.node_id, model, "preparation_required", "model_not_advertised", key, node.status.value)

    def prepare(self, node_id: str, model: ModelArtifactSpec, *, authorized: bool = False) -> ModelPreparationResult:
        plan = self.plan(node_id, model)
        if plan.status != "preparation_required":
            return ModelPreparationResult(plan)
        if not authorized:
            return ModelPreparationResult(
                ModelPreparationPlan(plan.node_id, plan.model, "manual_action_required", "installation_confirmation_required", plan.idempotency_key, plan.node_status)
            )
        if self.transport is None:
            return ModelPreparationResult(
                ModelPreparationPlan(plan.node_id, plan.model, "blocked", "preparation_transport_unavailable", plan.idempotency_key, plan.node_status)
            )
        node = self.registry.get(node_id)
        request = {
            "operation": "prepare_model",
            "node_id": node.node_id,
            "model": model.to_dict(),
            "idempotency_key": plan.idempotency_key,
        }
        try:
            response = self.transport(node, request)
        except Exception:
            return ModelPreparationResult(
                ModelPreparationPlan(plan.node_id, plan.model, "failed", "preparation_transport_failed", plan.idempotency_key, plan.node_status)
            )
        if not isinstance(response, Mapping):
            raise ModelPreparationError("preparation transport returned a non-object response")
        returned_digest = str(response.get("artifact_digest") or "").lower().removeprefix("sha256:")
        expected_digest = model.artifact_digest.lower().removeprefix("sha256:")
        if returned_digest and returned_digest != expected_digest:
            raise ModelPreparationError("preparation response artifact digest mismatch")
        if str(response.get("model_id") or model.model_id) != model.model_id:
            raise ModelPreparationError("preparation response model binding mismatch")
        status = "prepared" if str(response.get("status") or "prepared") in {"prepared", "ready", "available"} else "failed"
        reason = "preparation_accepted" if status == "prepared" else "preparation_rejected"
        result_plan = ModelPreparationPlan(plan.node_id, plan.model, status, reason, plan.idempotency_key, plan.node_status)
        return ModelPreparationResult(result_plan, dict(response))


__all__ = [
    "ModelArtifactSpec",
    "ModelPreparationCoordinator",
    "ModelPreparationError",
    "ModelPreparationPlan",
    "ModelPreparationResult",
]
