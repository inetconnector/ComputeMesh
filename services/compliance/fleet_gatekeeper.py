"""Server-side gatekeeper enforcing Provider verification and context-aware Fleet Governance.

Ensures that no fleet may enter the active marketplace or receive compute workloads
without satisfying the specific requirements applicable to the target marketplace mode
(Public Intermediary, Reseller, B2B, or Private Cluster).
"""
from __future__ import annotations

from typing import Any, Callable

from .provider_identity import (
    ComplianceEvaluation,
    ContractCounterpartyModel,
    CustomerAudience,
    IdentityVerificationState,
    MarketplaceMode,
    ProviderIdentity,
    evaluate_provider_requirements,
)
from .provider_identity_store import ProviderIdentityStore


class FleetGatekeeperError(Exception):
    def __init__(self, code: str, message: str, missing_requirements: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.missing_requirements = missing_requirements or []


class FleetGatekeeper:
    """Centralized context-aware enforcement gatekeeper for Fleet creation and Marketplace operation."""

    def __init__(
        self,
        identity_store: ProviderIdentityStore,
        stripe_profile_provider: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.identity_store = identity_store
        self.stripe_profile_provider = stripe_profile_provider

    def can_create_fleet(self, account_id: str) -> tuple[bool, str | None, list[dict[str, Any]]]:
        """Validates whether an account can create a new fleet (draft or active)."""
        if not account_id or not isinstance(account_id, str):
            return False, "invalid_account_id", []
        # Fleet draft creation is permitted; operational activation is gated by mode
        return True, None, []

    def evaluate_account_compliance(
        self,
        account_id: str,
        *,
        marketplace_mode: MarketplaceMode | str = MarketplaceMode.PUBLIC_INTERMEDIARY,
        counterparty_model: ContractCounterpartyModel | str = ContractCounterpartyModel.CUSTOMER_PROVIDER,
        customer_audience: CustomerAudience | str = CustomerAudience.CONSUMER_ALLOWED,
    ) -> ComplianceEvaluation:
        """Returns the full compliance evaluation for an account under the given marketplace mode."""
        identity = self.identity_store.get_identity_by_account(account_id)
        operator_profile = self.identity_store.get_operator_profile()

        if identity is None:
            return evaluate_provider_requirements(
                None, [], [],
                marketplace_mode=marketplace_mode,
                counterparty_model=counterparty_model,
                customer_audience=customer_audience,
                operator_profile=operator_profile,
            )

        declarations = self.identity_store.list_declarations(identity.provider_identity_id)
        evidence = self.identity_store.list_evidence(identity.provider_identity_id)

        stripe_profile = None
        if self.stripe_profile_provider is not None:
            try:
                stripe_profile = self.stripe_profile_provider(account_id)
            except Exception:
                stripe_profile = None

        return evaluate_provider_requirements(
            identity,
            declarations,
            evidence,
            stripe_profile,
            marketplace_mode=marketplace_mode,
            counterparty_model=counterparty_model,
            customer_audience=customer_audience,
            operator_profile=operator_profile,
        )

    def can_operate_marketplace(
        self,
        account_id: str,
        fleet_id: str,
        *,
        marketplace_mode: MarketplaceMode | str = MarketplaceMode.PUBLIC_INTERMEDIARY,
        counterparty_model: ContractCounterpartyModel | str = ContractCounterpartyModel.CUSTOMER_PROVIDER,
        customer_audience: CustomerAudience | str = CustomerAudience.CONSUMER_ALLOWED,
    ) -> tuple[bool, str | None, list[dict[str, Any]]]:
        """Strict server-side gatekeeper check before a fleet can receive marketplace jobs."""
        evaluation = self.evaluate_account_compliance(
            account_id,
            marketplace_mode=marketplace_mode,
            counterparty_model=counterparty_model,
            customer_audience=customer_audience,
        )

        if not evaluation.eligible:
            state = evaluation.identity_state
            if state == IdentityVerificationState.SUSPENDED:
                code = "PROVIDER_SUSPENDED"
                msg = "Anbieterkonto ist derzeit suspendiert."
            elif state == IdentityVerificationState.REJECTED:
                code = "PROVIDER_VERIFICATION_FAILED"
                msg = "Anbieterverifikation wurde abgelehnt."
            elif state == IdentityVerificationState.UNVERIFIED:
                code = "PROVIDER_IDENTITY_REQUIRED"
                msg = "Für die Marketplace-Teilnahme ist ein vollständiges rechtliches Anbieterprofil erforderlich."
            elif any(r.code == "trader_declaration_missing" for r in evaluation.missing_requirements):
                code = "TRADER_DECLARATION_REQUIRED"
                msg = "Die gesetzliche Händler-Selbsterklärung gem. DSA Art. 30 muss akzeptiert werden."
            else:
                code = "PROVIDER_IDENTITY_INCOMPLETE"
                msg = "Anbieterprofil ist unvollständig oder noch in Prüfung."

            return False, code, [r.to_dict() for r in evaluation.missing_requirements]

        return True, None, []

    def can_operate_private_cluster(self, account_id: str, fleet_id: str) -> tuple[bool, str | None, list[dict[str, Any]]]:
        """Evaluates private cluster operation (requires verified provider identity, exempt from DSA Art. 30 declaration)."""
        return self.can_operate_marketplace(
            account_id,
            fleet_id,
            marketplace_mode=MarketplaceMode.PRIVATE_CLUSTER,
            counterparty_model=ContractCounterpartyModel.DIRECT_PRIVATE_MEMBER,
            customer_audience=CustomerAudience.PRIVATE_MEMBERS,
        )

    def can_operate_b2b_marketplace(self, account_id: str, fleet_id: str) -> tuple[bool, str | None, list[dict[str, Any]]]:
        """Evaluates B2B marketplace operation."""
        return self.can_operate_marketplace(
            account_id,
            fleet_id,
            marketplace_mode=MarketplaceMode.B2B_INTERMEDIARY,
            counterparty_model=ContractCounterpartyModel.CUSTOMER_PROVIDER,
            customer_audience=CustomerAudience.BUSINESS_ONLY,
        )

    def require_marketplace_eligibility(
        self,
        account_id: str,
        fleet_id: str,
        *,
        marketplace_mode: MarketplaceMode | str = MarketplaceMode.PUBLIC_INTERMEDIARY,
    ) -> None:
        """Raises FleetGatekeeperError if the fleet cannot operate in the marketplace."""
        allowed, code, missing = self.can_operate_marketplace(
            account_id, fleet_id, marketplace_mode=marketplace_mode
        )
        if not allowed:
            raise FleetGatekeeperError(
                code=code or "PROVIDER_IDENTITY_INCOMPLETE",
                message="Fleet is not eligible for marketplace operation due to missing provider compliance requirements",
                missing_requirements=missing,
            )
