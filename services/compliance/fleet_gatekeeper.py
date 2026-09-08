"""Server-side gatekeeper enforcing Provider & Trader verification before Fleet Marketplace operation.

Complies with DSA Art. 30/31 by ensuring that no fleet may enter the active
marketplace without a verified ProviderIdentity and an accepted versioned
DSA Art. 30 Trader Declaration.
"""
from __future__ import annotations

from typing import Any, Callable

from .provider_identity import (
    ComplianceEvaluation,
    ProviderIdentity,
    VerificationState,
    evaluate_provider_requirements,
)
from .provider_identity_store import ProviderIdentityStore


class FleetGatekeeperError(Exception):
    def __init__(self, code: str, message: str, missing_requirements: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.missing_requirements = missing_requirements or []


class FleetGatekeeper:
    """Centralized enforcement gatekeeper for Fleet creation and Marketplace operation."""

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
        # Fleet draft creation is permitted; full marketplace operation requires verified identity
        return True, None, []

    def evaluate_account_compliance(self, account_id: str) -> ComplianceEvaluation:
        """Returns the full compliance evaluation for an account."""
        identity = self.identity_store.get_identity_by_account(account_id)
        if identity is None:
            return evaluate_provider_requirements(None, [], [])

        declarations = self.identity_store.list_declarations(identity.provider_identity_id)
        evidence = self.identity_store.list_evidence(identity.provider_identity_id)

        stripe_profile = None
        if self.stripe_profile_provider is not None:
            try:
                stripe_profile = self.stripe_profile_provider(account_id)
            except Exception:
                stripe_profile = None

        return evaluate_provider_requirements(identity, declarations, evidence, stripe_profile)

    def can_operate_marketplace(
        self,
        account_id: str,
        fleet_id: str,
    ) -> tuple[bool, str | None, list[dict[str, Any]]]:
        """Strict server-side gatekeeper check before a fleet can receive marketplace jobs."""
        evaluation = self.evaluate_account_compliance(account_id)

        if not evaluation.eligible:
            state = evaluation.state
            if state == VerificationState.SUSPENDED:
                code = "PROVIDER_SUSPENDED"
                msg = "Anbieterkonto ist derzeit suspendiert."
            elif state == VerificationState.REJECTED:
                code = "PROVIDER_VERIFICATION_FAILED"
                msg = "Anbieterverifikation wurde abgelehnt."
            elif state == VerificationState.UNVERIFIED:
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

    def require_marketplace_eligibility(self, account_id: str, fleet_id: str) -> None:
        """Raises FleetGatekeeperError if the fleet cannot operate in the marketplace."""
        allowed, code, missing = self.can_operate_marketplace(account_id, fleet_id)
        if not allowed:
            raise FleetGatekeeperError(
                code=code or "PROVIDER_IDENTITY_INCOMPLETE",
                message="Fleet is not eligible for marketplace operation due to missing provider compliance requirements",
                missing_requirements=missing,
            )
