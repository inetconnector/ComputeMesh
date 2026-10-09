"""Safe automatic onboarding for newly discovered Mesh nodes.

Discovery is deliberately separated from trust. The coordinator may probe a
node and prepare it through injected adapters, but it never invents
credentials or treats an unverified discovery response as routable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .node_registry import NodeLifecycle, NodeRecord, NodeRegistry


class NodeOnboardingError(RuntimeError):
    """Raised when an onboarding observation cannot satisfy its contract."""


class NodeAuthenticationRequired(NodeOnboardingError):
    """Raised by a probe when the node requires explicit manual pairing."""


@dataclass(frozen=True)
class NodeOnboardingObservation:
    """Bounded probe output; it contains no credentials or private policy."""

    capabilities: tuple[str, ...]
    models: tuple[Mapping[str, Any], ...]
    profile_revision: int
    identity_key_id: str | None = None
    identity_evidence_digest: str | None = None
    principal_id: str | None = None
    preparation_digest: str | None = None
    benchmark_accepted: bool | None = None
    benchmark_metrics: Mapping[str, Any] = field(default_factory=dict)
    authentication_required: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.profile_revision, bool) or not 0 <= int(self.profile_revision) <= 2**63 - 1:
            raise ValueError("profile_revision must be a non-negative integer")
        if len(self.capabilities) > 256 or any(not 1 <= len(str(value)) <= 128 for value in self.capabilities):
            raise ValueError("capabilities are bounded")
        if len(self.models) > 512 or any(not isinstance(value, Mapping) for value in self.models):
            raise ValueError("models are bounded objects")
        if not isinstance(self.benchmark_metrics, Mapping) or len(self.benchmark_metrics) > 128:
            raise ValueError("benchmark_metrics must be a bounded object")
        for field_name in ("identity_key_id", "principal_id"):
            value = getattr(self, field_name)
            if value is not None and not 1 <= len(str(value)) <= 160:
                raise ValueError(f"{field_name} is bounded")
        if self.identity_evidence_digest is not None and not re.fullmatch(r"[A-Fa-f0-9]{64}", str(self.identity_evidence_digest)):
            raise ValueError("identity_evidence_digest must be a SHA-256 digest")
        if self.preparation_digest is not None and not re.fullmatch(r"[A-Fa-f0-9]{64}", str(self.preparation_digest)):
            raise ValueError("preparation_digest must be a SHA-256 digest")
        if self.benchmark_accepted is not None and not isinstance(self.benchmark_accepted, bool):
            raise ValueError("benchmark_accepted must be boolean or absent")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NodeOnboardingObservation":
        if not isinstance(value, Mapping):
            raise NodeOnboardingError("node probe returned a non-object")
        raw_models = value.get("models", ())
        raw_capabilities = value.get("capabilities", ())
        if not isinstance(raw_models, (list, tuple)) or not isinstance(raw_capabilities, (list, tuple, set)):
            raise NodeOnboardingError("node probe returned invalid capabilities or models")
        if any(not isinstance(item, Mapping) for item in raw_models):
            raise NodeOnboardingError("node probe returned a non-object model")
        try:
            return cls(
                capabilities=tuple(str(item) for item in raw_capabilities if str(item)),
                models=tuple(raw_models),
                profile_revision=int(value.get("profile_revision", -1)),
                identity_key_id=(str(value["identity_key_id"]) if value.get("identity_key_id") else None),
                identity_evidence_digest=(str(value["identity_evidence_digest"]) if value.get("identity_evidence_digest") else None),
                principal_id=(str(value["principal_id"]) if value.get("principal_id") else None),
                preparation_digest=(str(value["preparation_digest"]) if value.get("preparation_digest") else None),
                benchmark_accepted=value.get("benchmark_accepted"),
                benchmark_metrics=(value.get("benchmark_metrics") if value.get("benchmark_metrics") is not None else {}),
                authentication_required=bool(value.get("authentication_required", False)),
            )
        except (TypeError, ValueError) as exc:
            raise NodeOnboardingError("node probe returned an invalid observation") from exc


@dataclass(frozen=True)
class NodeOnboardingResult:
    status: str
    node: NodeRecord
    manual_pairing_required: bool = False
    reason: str = ""


Probe = Callable[[NodeRecord], NodeOnboardingObservation | Mapping[str, Any]]
Prepare = Callable[[NodeRecord], str]
Benchmark = Callable[[NodeRecord], tuple[bool, Mapping[str, Any]] | Mapping[str, Any]]


class NodeOnboardingCoordinator:
    """Drive discovery through quarantine, authentication and readiness gates."""

    def __init__(self, registry: NodeRegistry) -> None:
        self.registry = registry

    def _manual_pairing(self, node_id: str, reason: str) -> NodeOnboardingResult:
        node = self.registry.mark_authentication_required(node_id, reason=reason)
        return NodeOnboardingResult("manual_pairing_required", node, True, reason)

    def _quarantine(self, node_id: str, reason: str) -> NodeOnboardingResult:
        try:
            node = self.registry.quarantine(node_id, reason=reason)
        except Exception:
            node = self.registry.get(node_id)
        return NodeOnboardingResult("failed", node, False, reason)

    def onboard(
        self,
        *,
        node_id: str,
        endpoint: str,
        probe: Probe,
        prepare: Prepare | None = None,
        benchmark: Benchmark | None = None,
        discovery_source: str = "lan",
    ) -> NodeOnboardingResult:
        """Probe and prepare one discovered node without granting implicit trust."""
        if not callable(probe):
            raise TypeError("probe must be callable")
        node = self.registry.discover(node_id, endpoint, discovery_source=discovery_source)
        if node.status is NodeLifecycle.REVOKED:
            return NodeOnboardingResult("failed", node, False, "node_revoked")
        try:
            observed = probe(node)
            observation = (
                observed
                if isinstance(observed, NodeOnboardingObservation)
                else NodeOnboardingObservation.from_mapping(observed)
            )
        except NodeAuthenticationRequired as exc:
            return self._manual_pairing(node.node_id, str(exc) or "manual_pairing_required")
        except Exception:
            return self._quarantine(node.node_id, "probe_failed")

        if observation.authentication_required or not all((
            observation.identity_key_id,
            observation.identity_evidence_digest,
            observation.principal_id,
        )):
            return self._manual_pairing(node.node_id, "manual_pairing_required")

        try:
            node = self.registry.get(node.node_id)
            if node.status in {NodeLifecycle.DISCOVERED, NodeLifecycle.QUARANTINED, NodeLifecycle.FAILED}:
                node = self.registry.mark_reachable(node.node_id)
            if node.status is NodeLifecycle.REACHABLE:
                node = self.registry.record_capabilities(
                    node.node_id,
                    capabilities=observation.capabilities,
                    models=observation.models,
                    profile_revision=observation.profile_revision,
                )
            elif node.status in {NodeLifecycle.READY, NodeLifecycle.ACTIVE}:
                node = self.registry.refresh_verified_capabilities(
                    node.node_id,
                    capabilities=observation.capabilities,
                    models=observation.models,
                    profile_revision=observation.profile_revision,
                )
                return NodeOnboardingResult("ready", node, False, "capabilities_refreshed")
            if node.status is NodeLifecycle.CAPABILITY_PROBED:
                node = self.registry.verify_identity(
                    node.node_id,
                    identity_key_id=str(observation.identity_key_id),
                    evidence_digest=str(observation.identity_evidence_digest),
                )
            if node.status is NodeLifecycle.IDENTITY_VERIFIED:
                node = self.registry.mark_authenticated(
                    node.node_id,
                    principal_id=str(observation.principal_id),
                )
            if node.status is NodeLifecycle.AUTHENTICATED:
                preparation_digest = observation.preparation_digest
                if preparation_digest is None and prepare is not None:
                    preparation_digest = str(prepare(node))
                if not preparation_digest:
                    return NodeOnboardingResult("preparation_required", node, False, "preparation_required")
                node = self.registry.mark_prepared(node.node_id, preparation_digest=preparation_digest)
            if node.status is NodeLifecycle.PREPARED:
                accepted = observation.benchmark_accepted
                metrics = dict(observation.benchmark_metrics)
                if benchmark is not None:
                    result = benchmark(node)
                    if isinstance(result, tuple) and len(result) == 2:
                        accepted, raw_metrics = result
                        metrics = dict(raw_metrics)
                    elif isinstance(result, Mapping):
                        accepted = result.get("accepted")
                        metrics = dict(result.get("metrics") or result)
                if not isinstance(accepted, bool):
                    return NodeOnboardingResult("benchmark_required", node, False, "benchmark_required")
                node = self.registry.record_benchmark(node.node_id, accepted=accepted, metrics=metrics)
            if node.status in {NodeLifecycle.READY, NodeLifecycle.ACTIVE}:
                return NodeOnboardingResult("ready", node)
            return NodeOnboardingResult("quarantined", node, False, node.reason or node.status.value)
        except Exception:
            return self._quarantine(node.node_id, "onboarding_failed")


__all__ = [
    "NodeAuthenticationRequired",
    "NodeOnboardingCoordinator",
    "NodeOnboardingError",
    "NodeOnboardingObservation",
    "NodeOnboardingResult",
]
