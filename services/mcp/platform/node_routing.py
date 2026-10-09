"""Capability-aware routing over the public, minimized node inventory."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .node_registry import NodeLifecycle, NodeRecord


@dataclass(frozen=True)
class NodeRouteRequirement:
    model_id: str | None = None
    required_capabilities: frozenset[str] = frozenset()
    min_free_vram_bytes: int = 0
    min_context_tokens: int = 0
    allowed_node_ids: frozenset[str] = frozenset()
    excluded_node_ids: frozenset[str] = frozenset()
    min_decode_tokens_per_second: float = 0.0
    max_latency_ms: float | None = None
    preferred_node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.model_id is not None and not 1 <= len(str(self.model_id)) <= 256:
            raise ValueError("model_id must be 1..256 characters")
        if any(not 1 <= len(str(value)) <= 128 for value in self.required_capabilities):
            raise ValueError("required capabilities are bounded")
        for field_name in ("allowed_node_ids", "excluded_node_ids"):
            values = frozenset(str(value) for value in getattr(self, field_name))
            if len(values) > 1024 or any(not 1 <= len(value) <= 160 for value in values):
                raise ValueError(f"{field_name} are bounded node identifiers")
            object.__setattr__(self, field_name, values)
        if int(self.min_free_vram_bytes) < 0 or int(self.min_context_tokens) < 0:
            raise ValueError("minimum capacity requirements must be non-negative")
        try:
            min_decode = float(self.min_decode_tokens_per_second)
        except (TypeError, ValueError) as exc:
            raise ValueError("min_decode_tokens_per_second must be finite and non-negative") from exc
        if not math.isfinite(min_decode) or min_decode < 0:
            raise ValueError("min_decode_tokens_per_second must be finite and non-negative")
        object.__setattr__(self, "min_decode_tokens_per_second", min_decode)
        if self.max_latency_ms is not None:
            try:
                max_latency = float(self.max_latency_ms)
            except (TypeError, ValueError) as exc:
                raise ValueError("max_latency_ms must be finite and positive") from exc
            if not math.isfinite(max_latency) or max_latency <= 0:
                raise ValueError("max_latency_ms must be finite and positive")
            object.__setattr__(self, "max_latency_ms", max_latency)
        preferred: list[str] = []
        for value in self.preferred_node_ids:
            clean = str(value)
            if clean and clean not in preferred:
                preferred.append(clean)
        if len(preferred) > 1024 or any(not 1 <= len(value) <= 160 for value in preferred):
            raise ValueError("preferred_node_ids are bounded node identifiers")
        object.__setattr__(self, "preferred_node_ids", tuple(preferred))


@dataclass(frozen=True)
class NodeRouteCandidate:
    node_id: str
    endpoint: str
    model_id: str | None
    accepted: bool
    reasons: tuple[str, ...] = ()
    free_vram_bytes: int = 0
    context_tokens: int = 0
    capabilities: tuple[str, ...] = ()
    decode_tokens_per_second: float | None = None
    latency_ms: float | None = None
    preferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "endpoint": self.endpoint,
            "model_id": self.model_id,
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "free_vram_bytes": self.free_vram_bytes,
            "context_tokens": self.context_tokens,
            "capabilities": list(self.capabilities),
            "decode_tokens_per_second": self.decode_tokens_per_second,
            "latency_ms": self.latency_ms,
            "preferred": self.preferred,
        }


@dataclass(frozen=True)
class NodeRouteDecision:
    status: str
    selected: NodeRouteCandidate | None
    candidates: tuple[NodeRouteCandidate, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selected": self.selected.to_dict() if self.selected else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _model_id(model: Mapping[str, Any]) -> str | None:
    for key in ("id", "model", "name", "model_id"):
        value = model.get(key)
        if value:
            return str(value)
    return None


def _capacity(model: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = model.get(key)
        if isinstance(value, bool):
            continue
        try:
            if value is not None:
                return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _metric(model: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = model.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(normalized) and normalized >= 0:
            return normalized
    return None


class CapabilityAwareNodeRouter:
    """Select only from verified, prepared and benchmark-ready nodes."""

    def route(
        self,
        nodes: Sequence[NodeRecord],
        requirement: NodeRouteRequirement,
    ) -> NodeRouteDecision:
        candidates: list[NodeRouteCandidate] = []
        accepted: list[NodeRouteCandidate] = []
        preferred = {node_id: index for index, node_id in enumerate(requirement.preferred_node_ids)}
        for node in nodes:
            reasons: list[str] = []
            if node.status not in {NodeLifecycle.READY, NodeLifecycle.ACTIVE}:
                reasons.append("node_not_ready")
            if node.auth_required or not node.identity_key_id or not node.principal_id:
                reasons.append("node_not_authenticated")
            if requirement.allowed_node_ids and node.node_id not in requirement.allowed_node_ids:
                reasons.append("node_not_allowed")
            if node.node_id in requirement.excluded_node_ids:
                reasons.append("node_excluded_for_retry")
            capabilities = set(node.capabilities)
            model = None
            if requirement.model_id is not None:
                model = next((candidate for candidate in node.models if _model_id(candidate) == requirement.model_id), None)
                if model is None:
                    reasons.append("model_not_advertised")
            elif node.models:
                model = node.models[0]
            model_identifier = _model_id(model) if model is not None else requirement.model_id
            if model is not None:
                capabilities.update(str(value) for value in (model.get("capabilities") or ()) if str(value))
            missing = sorted(set(requirement.required_capabilities) - capabilities)
            if missing:
                reasons.append("missing_capabilities:" + ",".join(missing))
            free_vram = _capacity(model or {}, "free_vram_bytes", "available_vram_bytes", "vram_bytes")
            context_tokens = _capacity(model or {}, "context_tokens", "context_size", "max_context_tokens")
            decode_tokens_per_second = _metric(
                model or {},
                "decode_tokens_per_second",
                "decode_tps",
                "throughput_tokens_per_second",
                "tokens_per_second",
            )
            latency_ms = _metric(model or {}, "latency_ms", "estimated_latency_ms")
            if free_vram < int(requirement.min_free_vram_bytes):
                reasons.append("insufficient_vram")
            if context_tokens < int(requirement.min_context_tokens):
                reasons.append("insufficient_context")
            if requirement.min_decode_tokens_per_second > 0 and (
                decode_tokens_per_second is None
                or decode_tokens_per_second < requirement.min_decode_tokens_per_second
            ):
                reasons.append("insufficient_decode_throughput")
            if requirement.max_latency_ms is not None and (
                latency_ms is None or latency_ms > requirement.max_latency_ms
            ):
                reasons.append("latency_requirement_unverified")
            is_preferred = node.node_id in preferred
            candidate = NodeRouteCandidate(
                node_id=node.node_id,
                endpoint=node.endpoint,
                model_id=model_identifier,
                accepted=not reasons,
                reasons=tuple(reasons),
                free_vram_bytes=free_vram,
                context_tokens=context_tokens,
                capabilities=tuple(sorted(capabilities)),
                decode_tokens_per_second=decode_tokens_per_second,
                latency_ms=latency_ms,
                preferred=is_preferred,
            )
            candidates.append(candidate)
            if candidate.accepted:
                accepted.append(candidate)

        accepted.sort(key=lambda candidate: (
            0 if candidate.preferred else 1,
            preferred.get(candidate.node_id, len(preferred)),
            -(candidate.decode_tokens_per_second or 0.0),
            1 if candidate.latency_ms is None else 0,
            candidate.latency_ms if candidate.latency_ms is not None else float("inf"),
            -candidate.free_vram_bytes,
            -candidate.context_tokens,
            candidate.node_id,
        ))
        selected = accepted[0] if accepted else None
        return NodeRouteDecision(
            status="ROUTED" if selected is not None else "NO_CAPABLE_NODE",
            selected=selected,
            candidates=tuple(candidates),
        )
