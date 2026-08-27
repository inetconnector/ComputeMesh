"""Compliance-aware live provider registration for production scheduling."""
from __future__ import annotations

from services.compliance.policy import ProviderComplianceRegistry
from services.orchestrator.live_provider_registration import LiveProviderRegistration
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry


class ComplianceAwareLiveProviderRegistration(LiveProviderRegistration):
    """Publish a provider only after server-owned production eligibility succeeds."""

    def __init__(
        self,
        registry: LiveSharedRuntimeRegistry,
        *,
        compliance_registry: ProviderComplianceRegistry,
    ) -> None:
        super().__init__(registry)
        self.compliance_registry = compliance_registry

    def _publish_if_complete(self, node_id: str) -> None:
        # Never trust region/contract/privacy claims pushed by the provider itself.
        # Eligibility comes exclusively from operator-controlled state.
        self.compliance_registry.require_eligible(node_id)
        super()._publish_if_complete(node_id)
