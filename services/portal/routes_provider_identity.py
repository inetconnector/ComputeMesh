"""HTTP route handlers for ComputeMesh Provider Identity & Multi-Tier EU Digital Regulation Compliance.

Exposes REST APIs for:
- Viewing authenticated provider compliance status, applicability decisions & requirements
- Updating legal provider profile (Individual vs Business)
- Accepting versioned Legal & DSA Declarations
- Dynamic Public Trader / Provider Disclosure endpoint (Allowlisted Minimal vs DSA Art. 30 DTO)
- Admin compliance reviews and platform operator profile configuration
"""
from __future__ import annotations

from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
from typing import Any, Tuple

from services.compliance.dsa_policy import PlatformEnterpriseSize, PlatformOperatorLegalProfile
from services.compliance.fleet_gatekeeper import FleetGatekeeper
from services.compliance.provider_identity import (
    ContractCounterpartyModel,
    CustomerAudience,
    DSA_TRADER_DECLARATION_VERSION,
    EntityType,
    EvidenceSource,
    IdentityVerificationState,
    LegalDeclaration,
    MarketplaceMode,
    ProviderIdentity,
    StructuredAddress,
    evaluate_provider_requirements,
)
from services.compliance.provider_identity_store import (
    ProviderIdentityStore,
    ProviderIdentityStoreError,
)
from services.portal.passkey_routes import session_account_from_headers

logger = logging.getLogger("computemesh.routes_provider_identity")


def _resolve_provider_store_path() -> Path:
    raw = os.environ.get("COMPUTEMESH_PROVIDER_IDENTITY_DB_PATH", "").strip()
    if raw:
        return Path(raw)
    raw_fleet = os.environ.get("COMPUTEMESH_FLEET_ACCOUNTS_DB_PATH", "").strip()
    if raw_fleet:
        return Path(raw_fleet)
    return Path("/var/lib/computemesh/fleet_accounts.db")


def _build_provider_store() -> ProviderIdentityStore:
    try:
        return ProviderIdentityStore(_resolve_provider_store_path())
    except Exception:
        return ProviderIdentityStore(Path("/tmp/computemesh_provider_identity.db"))


PROVIDER_IDENTITY_STORE = _build_provider_store()
GATEKEEPER = FleetGatekeeper(PROVIDER_IDENTITY_STORE)


class PortalProviderIdentityHandler:
    """REST API Handlers for Provider Identity and Multi-Tier EU Compliance."""

    def __init__(
        self,
        store: ProviderIdentityStore | None = None,
        gatekeeper: FleetGatekeeper | None = None,
    ) -> None:
        self.store = store or PROVIDER_IDENTITY_STORE
        self.gatekeeper = gatekeeper or GATEKEEPER

    def get_provider_identity(
        self,
        headers: Any,
        marketplace_mode: str = "PUBLIC_INTERMEDIARY",
        counterparty_model: str = "CUSTOMER_PROVIDER",
        customer_audience: str = "CONSUMER_ALLOWED",
    ) -> Tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        operator_profile = self.store.get_operator_profile()
        identity = self.store.get_identity_by_account(account.account_id)

        if identity is None:
            evaluation = evaluate_provider_requirements(
                None, [], [],
                marketplace_mode=marketplace_mode,
                counterparty_model=counterparty_model,
                customer_audience=customer_audience,
                operator_profile=operator_profile,
            )
            return {
                "has_profile": False,
                "identity": None,
                "evaluation": evaluation.to_dict(),
                "operator_profile": operator_profile.to_dict(),
                "dsa_declaration_version": DSA_TRADER_DECLARATION_VERSION,
            }, HTTPStatus.OK, None

        declarations = self.store.list_declarations(identity.provider_identity_id)
        evidence = self.store.list_evidence(identity.provider_identity_id)
        evaluation = evaluate_provider_requirements(
            identity,
            declarations,
            evidence,
            marketplace_mode=marketplace_mode,
            counterparty_model=counterparty_model,
            customer_audience=customer_audience,
            operator_profile=operator_profile,
        )

        return {
            "has_profile": True,
            "identity": identity.to_dict(),
            "evaluation": evaluation.to_dict(),
            "declarations": [d.to_dict() for d in declarations],
            "evidence": [e.to_dict() for e in evidence],
            "operator_profile": operator_profile.to_dict(),
            "dsa_declaration_version": DSA_TRADER_DECLARATION_VERSION,
        }, HTTPStatus.OK, None

    def update_provider_identity(self, headers: Any, body: dict[str, Any]) -> Tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        try:
            entity_type_raw = str(body.get("entity_type", "individual")).strip().lower()
            if entity_type_raw not in {"individual", "business"}:
                return {"error": "entity_type must be 'individual' or 'business'"}, HTTPStatus.BAD_REQUEST, None

            legal_name = str(body.get("legal_name", "")).strip()
            if not legal_name or len(legal_name) < 2:
                return {"error": "Vollständiger rechtlicher Name ist erforderlich"}, HTTPStatus.BAD_REQUEST, None

            addr_data = body.get("address")
            if not isinstance(addr_data, dict):
                return {"error": "Gültige Adressdaten sind erforderlich"}, HTTPStatus.BAD_REQUEST, None

            address = StructuredAddress(
                line1=str(addr_data.get("line1", "")),
                line2=addr_data.get("line2"),
                postal_code=str(addr_data.get("postal_code", "")),
                city=str(addr_data.get("city", "")),
                state_province=addr_data.get("state_province"),
                country_code=str(addr_data.get("country_code", "DE")),
            )

            email = str(body.get("email", account.email)).strip().lower()

            reg_info = body.get("registry_info")
            if entity_type_raw == "business" and isinstance(reg_info, dict):
                reg_info = {
                    "registry_country": str(reg_info.get("registry_country", address.country_code)),
                    "registry_name": str(reg_info.get("registry_name", "")),
                    "registration_number": str(reg_info.get("registration_number", "")),
                }

            identity = self.store.upsert_identity(
                account_id=account.account_id,
                entity_type=EntityType(entity_type_raw),
                legal_name=legal_name,
                address=address,
                email=email,
                trade_name=body.get("trade_name"),
                legal_representative=body.get("legal_representative"),
                acting_person_relationship=body.get("acting_person_relationship"),
                phone=body.get("phone"),
                registry_info=reg_info,
                vat_id=body.get("vat_id"),
                actor=f"user:{account.account_id}",
            )

            declarations = self.store.list_declarations(identity.provider_identity_id)
            evidence = self.store.list_evidence(identity.provider_identity_id)
            operator_profile = self.store.get_operator_profile()
            evaluation = evaluate_provider_requirements(
                identity, declarations, evidence, operator_profile=operator_profile
            )

            return {
                "status": "ok",
                "identity": identity.to_dict(),
                "evaluation": evaluation.to_dict(),
            }, HTTPStatus.OK, None

        except ValueError as exc:
            return {"error": str(exc)}, HTTPStatus.BAD_REQUEST, None
        except ProviderIdentityStoreError as exc:
            return {"error": str(exc)}, HTTPStatus.BAD_REQUEST, None
        except Exception as exc:
            logger.exception("Unexpected error updating provider identity")
            return {"error": f"Internal error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR, None

    def accept_trader_declaration(
        self,
        headers: Any,
        body: dict[str, Any],
        client_address: tuple[str, int] | None = None,
    ) -> Tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        identity = self.store.get_identity_by_account(account.account_id)
        if identity is None:
            return {"error": "Bitte erstelle zuerst ein Anbieterprofil, bevor du die Erklärung abgibst."}, HTTPStatus.BAD_REQUEST, None

        version = str(body.get("legal_text_version", body.get("version", DSA_TRADER_DECLARATION_VERSION))).strip()
        decl_type = str(body.get("declaration_type", "DSA_ART30_TRADER_COMMITMENT")).strip()
        locale = str(body.get("locale", "de")).strip()[:5]
        context = str(body.get("applicability_context", "PUBLIC_MARKETPLACE")).strip()

        client_ip = ""
        if client_address and isinstance(client_address, tuple) and len(client_address) >= 1:
            client_ip = str(client_address[0])

        decl = self.store.record_declaration(
            provider_identity_id=identity.provider_identity_id,
            account_id=account.account_id,
            legal_text_version=version,
            declaration_type=decl_type,
            locale=locale,
            client_ip=client_ip,
            applicability_context=context,
        )

        declarations = self.store.list_declarations(identity.provider_identity_id)
        evidence = self.store.list_evidence(identity.provider_identity_id)
        operator_profile = self.store.get_operator_profile()
        evaluation = evaluate_provider_requirements(
            identity, declarations, evidence, operator_profile=operator_profile
        )

        return {
            "status": "accepted",
            "declaration": decl.to_dict(),
            "evaluation": evaluation.to_dict(),
        }, HTTPStatus.OK, None

    def get_public_trader_profile(
        self,
        provider_identity_id: str,
        marketplace_mode: str = "PUBLIC_INTERMEDIARY",
    ) -> Tuple[dict[str, Any], HTTPStatus, str | None]:
        """Public Marketplace transparency endpoint returning filtered allowlist DTO."""
        clean_id = str(provider_identity_id or "").strip()
        if not clean_id:
            return {"error": "provider_identity_id is required"}, HTTPStatus.BAD_REQUEST, None

        identity = self.store.get_identity(clean_id)
        if identity is None:
            return {"error": "Provider not found"}, HTTPStatus.NOT_FOUND, None

        declarations = self.store.list_declarations(identity.provider_identity_id)
        evidence = self.store.list_evidence(identity.provider_identity_id)
        operator_profile = self.store.get_operator_profile()
        evaluation = evaluate_provider_requirements(
            identity, declarations, evidence,
            marketplace_mode=marketplace_mode,
            operator_profile=operator_profile,
        )

        dsa_applicable = evaluation.applicability_decision.article_30_applicable
        has_decl = any(
            d.version == DSA_TRADER_DECLARATION_VERSION and d.accepted_at
            for d in declarations
        )

        public_dto = identity.to_public_profile(
            declaration_accepted=has_decl,
            dsa_applicable=dsa_applicable,
        )

        return {
            "profile": public_dto.to_dict(),
            "disclosure_type": "DSA_ARTICLE_30" if dsa_applicable else "MINIMAL_PROVIDER",
            "dsa_applicable": dsa_applicable,
        }, HTTPStatus.OK, None

    def admin_review_provider(
        self,
        headers: Any,
        body: dict[str, Any],
    ) -> Tuple[dict[str, Any], HTTPStatus, str | None]:
        """Admin manual review endpoint with mandatory audit reasoning."""
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        if getattr(account, "role", "") != "admin":
            return {"error": "forbidden: requires admin capability"}, HTTPStatus.FORBIDDEN, None

        provider_identity_id = str(body.get("provider_identity_id", "")).strip()
        new_state_raw = str(body.get("new_state", "")).strip().upper()
        reason = str(body.get("reason", "")).strip()

        if not provider_identity_id:
            return {"error": "provider_identity_id is required"}, HTTPStatus.BAD_REQUEST, None
        if new_state_raw not in IdentityVerificationState.__members__:
            return {"error": f"Invalid verification state: {new_state_raw}"}, HTTPStatus.BAD_REQUEST, None
        if not reason or len(reason) < 5:
            return {"error": "A clear statement of reason (min 5 chars) is mandatory for audit trail"}, HTTPStatus.BAD_REQUEST, None

        target_state = IdentityVerificationState[new_state_raw]
        try:
            updated = self.store.update_verification_state(
                provider_identity_id,
                target_state,
                actor=f"admin:{account.account_id}",
                reason=reason,
            )
            return {
                "status": "ok",
                "identity": updated.to_dict(),
            }, HTTPStatus.OK, None
        except ProviderIdentityStoreError as exc:
            return {"error": str(exc)}, HTTPStatus.BAD_REQUEST, None
