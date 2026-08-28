"""Global mesh trust/privacy policy primitives.

Trust tier and execution privacy are deliberately orthogonal. The evaluator is
fail-closed: a requested privacy class is never silently weakened to fit an
available provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
from typing import FrozenSet, Iterable


class ProviderTrustTier(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    RESTRICTED = "RESTRICTED"


class ExecutionPrivacyClass(str, Enum):
    PUBLIC = "PUBLIC"
    CONFIDENTIAL = "CONFIDENTIAL"
    CRYPTO_PRIVATE = "CRYPTO_PRIVATE"


_TRUST_RANK = {
    ProviderTrustTier.OPEN: 0,
    ProviderTrustTier.VERIFIED: 1,
    ProviderTrustTier.RESTRICTED: 2,
}


@dataclass(frozen=True)
class MeshFeatureFlags:
    """Runtime gates. Protected execution defaults OFF."""

    confidential_execution: bool = False
    crypto_private_execution: bool = False

    @classmethod
    def from_env(cls) -> "MeshFeatureFlags":
        return cls(
            confidential_execution=os.environ.get(
                "COMPUTEMESH_CONFIDENTIAL_EXECUTION_ENABLED", ""
            ).strip() == "1",
            crypto_private_execution=os.environ.get(
                "COMPUTEMESH_CRYPTO_PRIVATE_ENABLED", ""
            ).strip() == "1",
        )


@dataclass(frozen=True)
class JobRoutingPolicy:
    privacy_class: ExecutionPrivacyClass
    minimum_trust_tier: ProviderTrustTier = ProviderTrustTier.OPEN
    allowed_regions: FrozenSet[str] = field(default_factory=frozenset)
    required_crypto_capabilities: FrozenSet[str] = field(default_factory=frozenset)

    @classmethod
    def public(
        cls,
        *,
        minimum_trust_tier: ProviderTrustTier = ProviderTrustTier.OPEN,
        allowed_regions: Iterable[str] = (),
    ) -> "JobRoutingPolicy":
        return cls(
            privacy_class=ExecutionPrivacyClass.PUBLIC,
            minimum_trust_tier=minimum_trust_tier,
            allowed_regions=frozenset(x.upper() for x in allowed_regions),
        )


@dataclass(frozen=True)
class ProviderRoutingCapabilities:
    node_id: str
    trust_tier: ProviderTrustTier
    region: str
    production_eligible: bool
    technically_compatible: bool
    plaintext_logging_enabled: bool = False
    confidential_execution_supported: bool = False
    confidential_technology: str | None = None
    attestation_verified: bool = False
    attestation_fresh: bool = False
    crypto_private_capabilities: FrozenSet[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str


def evaluate_mesh_eligibility(
    job: JobRoutingPolicy,
    provider: ProviderRoutingCapabilities,
    *,
    features: MeshFeatureFlags | None = None,
) -> EligibilityDecision:
    """Evaluate the routing intersection without privacy downgrade."""
    features = features or MeshFeatureFlags.from_env()

    if not provider.node_id:
        return EligibilityDecision(False, "provider node_id is missing")
    if not provider.production_eligible:
        return EligibilityDecision(False, "provider is not production eligible")
    if not provider.technically_compatible:
        return EligibilityDecision(False, "provider is not technically compatible")
    if _TRUST_RANK[provider.trust_tier] < _TRUST_RANK[job.minimum_trust_tier]:
        return EligibilityDecision(False, "provider trust tier is below job minimum")
    if job.allowed_regions and provider.region.upper() not in job.allowed_regions:
        return EligibilityDecision(False, "provider region is outside job policy")

    if job.privacy_class is ExecutionPrivacyClass.PUBLIC:
        return EligibilityDecision(True, "PUBLIC workload admitted by technical/trust/region policy")

    # Protected work is never eligible for OPEN/plaintext workers.
    if provider.trust_tier is ProviderTrustTier.OPEN:
        return EligibilityDecision(False, "protected workload cannot run on OPEN provider")
    if provider.plaintext_logging_enabled:
        return EligibilityDecision(False, "protected workload cannot run with plaintext logging")

    if job.privacy_class is ExecutionPrivacyClass.CONFIDENTIAL:
        if not features.confidential_execution:
            return EligibilityDecision(False, "confidential execution feature is disabled")
        if not provider.confidential_execution_supported:
            return EligibilityDecision(False, "provider does not support confidential execution")
        technology = (provider.confidential_technology or "").strip().lower()
        if not technology or technology in {"none", "generic", "simulated", "tls", "container", "vm"}:
            return EligibilityDecision(False, "no concrete confidential technology is declared")
        if not provider.attestation_verified or not provider.attestation_fresh:
            return EligibilityDecision(False, "confidential attestation is absent, invalid, or stale")
        return EligibilityDecision(True, "CONFIDENTIAL workload passed explicit fail-closed gates")

    if job.privacy_class is ExecutionPrivacyClass.CRYPTO_PRIVATE:
        if not features.crypto_private_execution:
            return EligibilityDecision(False, "crypto-private execution feature is disabled")
        missing = job.required_crypto_capabilities - provider.crypto_private_capabilities
        if missing:
            return EligibilityDecision(
                False,
                "provider lacks required crypto-private capabilities: " + ",".join(sorted(missing)),
            )
        return EligibilityDecision(True, "CRYPTO_PRIVATE workload passed capability gates")

    return EligibilityDecision(False, "unsupported privacy class")
