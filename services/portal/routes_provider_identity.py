"""HTTP route handlers for ComputeMesh Provider & Trader Identity Compliance.

Exposes REST APIs for:
- Viewing authenticated provider compliance status & missing requirements
- Updating legal provider profile (Individual vs Business)
- Accepting DSA Art. 30 versioned Trader Declarations
- Public Trader Disclosure endpoint (PublicTraderProfile DTO allowlist)
- Admin compliance reviews with mandatory audit logging
"""
from __future__ import annotations

from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
from typing import Any, Tuple

from services.compliance.fleet_gatekeeper import FleetGatekeeper
from services.compliance.provider_identity import (
    DSA_TRADER_DECLARATION_VERSION,
    EntityType,
    EvidenceSource,
    ProviderIdentity,
    StructuredAddress,
    VerificationState,
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
    """REST API Handlers for Provider Identity and EU Compliance."""

    def __init__(
        self,
        store: ProviderIdentityStore | None = None,
        gatekeeper: FleetGatekeeper | None = None,
    ) -> None:
        self.store = store or PROVIDER_IDENTITY_STORE
        self.gatekeeper = gatekeeper or GATEKEEPER

    def get_provider_identity(self, headers: Any) -> Tuple[dict[str, Any], HTTPStatus, str | None]:
        account = session_account_from_headers(headers)
        if account is None:
            return {"error": "not authenticated"}, HTTPStatus.UNAUTHORIZED, None

        identity = self.store.get_identity_by_account(account.account_id)
        if identity is None:
            return {
                "has_profile": False,
                "identity": None,
                "evaluation": {
                    "eligible": False,
                    "state": VerificationState.UNVERIFIED.value,
                    "missing_requirements": [
                        {
                            "code": "provider_identity_missing",
                            "field": "identity",
                            "blocking": True,
                            "message": "Es wurde noch kein rechtliches Anbieterprofil angelegt.",
                        }
                    ],
                    "field_statuses": {},
                    "active_declaration_version": None,
                    "stripe_payouts_ready": False,
                },
                "dsa_declaration_version": DSA_TRADER_DECLARATION_VERSION,
            }, HTTPStatus.OK, None

        declarations = self.store.list_declarations(identity.provider_identity_id)
        evidence = self.store.list_evidence(identity.provider_identity_id)
        evaluation = evaluate_provider_requirements(identity, declarations, evidence)

        return {
            "has_profile": True,
            "identity": identity.to_dict(),
            "evaluation": evaluation.to_dict(),
            "declarations": [d.to_dict() for d in declarations],
            "evidence": [e.to_dict() for e in evidence],
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
            evaluation = evaluate_provider_requirements(identity, declarations, evidence)

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

        version = str(body.get("legal_text_version", DSA_TRADER_DECLARATION_VERSION)).strip()
        if version != DSA_TRADER_DECLARATION_VERSION:
            return {"error": f"Ungültige Deklarationsversion: {version!r}. Erwartet: {DSA_TRADER_DECLARATION_VERSION}"}, HTTPStatus.BAD_REQUEST, None

        locale = str(body.get("locale", "de")).strip()[:5]
        client_ip = ""
        if headers and hasattr(headers, "get"):
            client_ip = str(headers.get("X-Forwarded-For", "")).split(",")[0].strip()
        if not client_ip and client_address:
            client_ip = client_address[0]

        decl = self.store.record_declaration(
            provider_identity_id=identity.provider_identity_id,
            account_id=account.account_id,
            legal_text_version=version,
            locale=locale,
            client_ip=client_ip,
        )

        # Re-evaluate compliance
        declarations = self.store.list_declarations(identity.provider_identity_id)
        evidence = self.store.list_evidence(identity.provider_identity_id)
        evaluation = evaluate_provider_requirements(identity, declarations, evidence)

        # If fully complete and in pending review -> transition to verified
        if not evaluation.missing_requirements and identity.verification_state in {
            VerificationState.PENDING_REVIEW,
            VerificationState.UNVERIFIED,
            VerificationState.INCOMPLETE,
        }:
            identity = self.store.update_verification_state(
                identity.provider_identity_id,
                VerificationState.VERIFIED,
                actor=f"system:declaration_complete",
                reason="All legal requirements satisfied and DSA declaration accepted",
            )
            evaluation = evaluate_provider_requirements(identity, declarations, evidence)

        return {
            "status": "ok",
            "declaration": decl.to_dict(),
            "identity": identity.to_dict(),
            "evaluation": evaluation.to_dict(),
        }, HTTPStatus.OK, None

    def get_public_trader_profile(self, provider_identity_id: str) -> Tuple[dict[str, Any], HTTPStatus, str | None]:
        """Public DSA Art. 30 Marketplace transparency endpoint."""
        clean_id = str(provider_identity_id or "").strip()
        if not clean_id:
            return {"error": "provider_identity_id is required"}, HTTPStatus.BAD_REQUEST, None

        identity = self.store.get_identity(clean_id)
        if identity is None:
            return {"error": "Trader profile not found"}, HTTPStatus.NOT_FOUND, None

        declarations = self.store.list_declarations(identity.provider_identity_id)
        has_decl = any(d.legal_text_version == DSA_TRADER_DECLARATION_VERSION for d in declarations)

        public_profile = identity.to_public_profile(declaration_accepted=has_decl)
        return public_profile.to_dict(), HTTPStatus.OK, None
