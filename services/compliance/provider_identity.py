"""Domain models and requirement evaluation for ComputeMesh Provider and Trader Identity.

Complies with:
- Regulation (EU) 2022/2065 (Digital Services Act, Art. 30 & 31 - Traceability of Traders & Compliance by Design)
- Regulation (EU) 2016/679 (GDPR, Art. 5, 6, 25, 32 - Data Minimization, Lawfulness, Privacy by Design)
- Regulation (EU) 2019/1150 (P2B Regulation - Transparent suspension and operational terms)

Domain Separation:
1. ComputeMesh Account (facc_...): User login / Passkey auth
2. Provider / Trader Identity (prv_...): Legal individual or business entity operating fleets
3. Fleet(s): Operational compute clusters owned by a Provider Identity
4. Stripe Connect: Payment, payout and financial regulatory KYC (Stripe is the payment KYC provider)
5. ControlPlane Governance: Fleet scheduling, placement and lease draining without raw PII
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

DSA_TRADER_DECLARATION_VERSION = "dsa_art30_v1.0"
ISO_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EntityType(str, Enum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class VerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    INCOMPLETE = "INCOMPLETE"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REVERIFICATION_REQUIRED = "REVERIFICATION_REQUIRED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class EvidenceSource(str, Enum):
    SELF_ATTESTATION = "SELF_ATTESTATION"
    STRIPE_CONNECT = "STRIPE_CONNECT"
    COMMERCIAL_REGISTER = "COMMERCIAL_REGISTER"
    VAT_VIES = "VAT_VIES"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    EUDI_WALLET = "EUDI_WALLET"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StructuredAddress:
    line1: str
    city: str
    postal_code: str
    country_code: str
    line2: str | None = None
    state_province: str | None = None

    def __post_init__(self) -> None:
        country = str(self.country_code or "").strip().upper()
        if not ISO_COUNTRY_CODE_RE.match(country):
            raise ValueError(f"Invalid ISO 3166-1 alpha-2 country code: {self.country_code!r}")
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "line1", str(self.line1 or "").strip())
        object.__setattr__(self, "city", str(self.city or "").strip())
        object.__setattr__(self, "postal_code", str(self.postal_code or "").strip())
        if self.line2 is not None:
            object.__setattr__(self, "line2", str(self.line2).strip() or None)
        if self.state_province is not None:
            object.__setattr__(self, "state_province", str(self.state_province).strip() or None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuredAddress:
        return cls(
            line1=data.get("line1", ""),
            line2=data.get("line2"),
            postal_code=data.get("postal_code", ""),
            city=data.get("city", ""),
            state_province=data.get("state_province"),
            country_code=data.get("country_code", ""),
        )


@dataclass(frozen=True)
class BusinessRegistryInfo:
    registry_country: str
    registry_name: str
    registration_number: str

    def __post_init__(self) -> None:
        country = str(self.registry_country or "").strip().upper()
        if not ISO_COUNTRY_CODE_RE.match(country):
            raise ValueError(f"Invalid ISO 3166-1 alpha-2 registry country code: {self.registry_country!r}")
        object.__setattr__(self, "registry_country", country)
        object.__setattr__(self, "registry_name", str(self.registry_name or "").strip())
        object.__setattr__(self, "registration_number", str(self.registration_number or "").strip())

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BusinessRegistryInfo:
        return cls(
            registry_country=data.get("registry_country", ""),
            registry_name=data.get("registry_name", ""),
            registration_number=data.get("registration_number", ""),
        )


@dataclass(frozen=True)
class IdentityEvidence:
    evidence_id: str
    provider_identity_id: str
    field_scope: str
    source: EvidenceSource
    status: str
    verified_at: str
    verification_method: str
    evidence_reference: str = ""
    expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "provider_identity_id": self.provider_identity_id,
            "field_scope": self.field_scope,
            "source": self.source.value if isinstance(self.source, EvidenceSource) else str(self.source),
            "status": self.status,
            "verified_at": self.verified_at,
            "expires_at": self.expires_at,
            "evidence_reference": self.evidence_reference,
            "verification_method": self.verification_method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdentityEvidence:
        source_val = data.get("source")
        source = EvidenceSource(source_val) if isinstance(source_val, str) else EvidenceSource.SELF_ATTESTATION
        return cls(
            evidence_id=str(data.get("evidence_id", "")),
            provider_identity_id=str(data.get("provider_identity_id", "")),
            field_scope=str(data.get("field_scope", "")),
            source=source,
            status=str(data.get("status", "valid")),
            verified_at=str(data.get("verified_at", "")),
            verification_method=str(data.get("verification_method", "")),
            evidence_reference=str(data.get("evidence_reference", "")),
            expires_at=data.get("expires_at"),
        )


@dataclass(frozen=True)
class TraderDeclaration:
    declaration_id: str
    provider_identity_id: str
    account_id: str
    legal_text_version: str
    accepted_at: str
    locale: str = "de"
    ip_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraderDeclaration:
        return cls(
            declaration_id=str(data.get("declaration_id", "")),
            provider_identity_id=str(data.get("provider_identity_id", "")),
            account_id=str(data.get("account_id", "")),
            legal_text_version=str(data.get("legal_text_version", DSA_TRADER_DECLARATION_VERSION)),
            accepted_at=str(data.get("accepted_at", "")),
            locale=str(data.get("locale", "de")),
            ip_hash=str(data.get("ip_hash", "")),
        )


@dataclass(frozen=True)
class ProviderIdentity:
    provider_identity_id: str
    account_id: str
    entity_type: EntityType
    legal_name: str
    address: StructuredAddress
    email: str
    trade_name: str | None = None
    legal_representative: str | None = None
    acting_person_relationship: str | None = None
    phone: str | None = None
    registry_info: BusinessRegistryInfo | None = None
    vat_id: str | None = None
    verification_state: VerificationState = VerificationState.UNVERIFIED
    state_reason: str | None = None
    stripe_account_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    verified_at: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_identity_id": self.provider_identity_id,
            "account_id": self.account_id,
            "entity_type": self.entity_type.value if isinstance(self.entity_type, EntityType) else str(self.entity_type),
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "legal_representative": self.legal_representative,
            "acting_person_relationship": self.acting_person_relationship,
            "address": self.address.to_dict() if self.address else None,
            "email": self.email,
            "phone": self.phone,
            "registry_info": self.registry_info.to_dict() if self.registry_info else None,
            "vat_id": self.vat_id,
            "verification_state": self.verification_state.value if isinstance(self.verification_state, VerificationState) else str(self.verification_state),
            "state_reason": self.state_reason,
            "stripe_account_id": self.stripe_account_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "verified_at": self.verified_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderIdentity:
        entity_type_raw = data.get("entity_type")
        entity_type = EntityType(entity_type_raw) if isinstance(entity_type_raw, str) else EntityType.INDIVIDUAL
        state_raw = data.get("verification_state")
        verification_state = VerificationState(state_raw) if isinstance(state_raw, str) else VerificationState.UNVERIFIED

        addr_data = data.get("address")
        address = StructuredAddress.from_dict(addr_data) if isinstance(addr_data, dict) else StructuredAddress(
            line1="", city="", postal_code="", country_code="DE"
        )

        reg_data = data.get("registry_info")
        registry_info = BusinessRegistryInfo.from_dict(reg_data) if isinstance(reg_data, dict) and reg_data.get("registration_number") else None

        return cls(
            provider_identity_id=str(data.get("provider_identity_id", "")),
            account_id=str(data.get("account_id", "")),
            entity_type=entity_type,
            legal_name=str(data.get("legal_name", "")).strip(),
            trade_name=str(data["trade_name"]).strip() if data.get("trade_name") else None,
            legal_representative=str(data["legal_representative"]).strip() if data.get("legal_representative") else None,
            acting_person_relationship=str(data["acting_person_relationship"]).strip() if data.get("acting_person_relationship") else None,
            address=address,
            email=str(data.get("email", "")).strip().lower(),
            phone=str(data["phone"]).strip() if data.get("phone") else None,
            registry_info=registry_info,
            vat_id=str(data["vat_id"]).strip() if data.get("vat_id") else None,
            verification_state=verification_state,
            state_reason=str(data["state_reason"]) if data.get("state_reason") else None,
            stripe_account_id=str(data["stripe_account_id"]).strip() if data.get("stripe_account_id") else None,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            verified_at=str(data["verified_at"]) if data.get("verified_at") else None,
            schema_version=int(data.get("schema_version", 1)),
        )

    def to_public_profile(self, *, declaration_accepted: bool = True) -> PublicTraderProfile:
        """Strict allowlist serializer for public DSA Art. 30 Marketplace transparency."""
        public_name = self.trade_name or self.legal_name
        return PublicTraderProfile(
            provider_identity_id=self.provider_identity_id,
            entity_type=self.entity_type.value,
            trade_or_legal_name=public_name,
            country_code=self.address.country_code,
            city=self.address.city,
            postal_code=self.address.postal_code,
            business_registry=self.registry_info.to_dict() if self.registry_info else None,
            contact_email=self.email,
            verification_status=self.verification_state.value,
            trader_declaration_active=declaration_accepted,
        )


@dataclass(frozen=True)
class PublicTraderProfile:
    """Strictly filtered public DTO for DSA Art. 30 Marketplace transparency."""
    provider_identity_id: str
    entity_type: str
    trade_or_legal_name: str
    country_code: str
    city: str
    postal_code: str
    contact_email: str
    verification_status: str
    trader_declaration_active: bool
    business_registry: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MissingRequirement:
    code: str
    field: str
    blocking: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComplianceEvaluation:
    eligible: bool
    state: VerificationState
    missing_requirements: list[MissingRequirement] = field(default_factory=list)
    field_statuses: dict[str, str] = field(default_factory=dict)
    active_declaration_version: str | None = None
    stripe_payouts_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "state": self.state.value,
            "missing_requirements": [r.to_dict() for r in self.missing_requirements],
            "field_statuses": self.field_statuses,
            "active_declaration_version": self.active_declaration_version,
            "stripe_payouts_ready": self.stripe_payouts_ready,
        }


def evaluate_provider_requirements(
    identity: ProviderIdentity | None,
    declarations: list[TraderDeclaration],
    evidence_list: list[IdentityEvidence],
    stripe_profile: dict[str, Any] | None = None,
) -> ComplianceEvaluation:
    """Evaluates DSA Art. 30 & GDPR provider compliance fail-closed."""
    missing: list[MissingRequirement] = []
    field_statuses: dict[str, str] = {}

    if identity is None:
        missing.append(MissingRequirement(
            code="provider_identity_missing",
            field="identity",
            blocking=True,
            message="Ein rechtliches Anbieterprofil (Betreiberidentität) muss angelegt werden.",
        ))
        return ComplianceEvaluation(
            eligible=False,
            state=VerificationState.UNVERIFIED,
            missing_requirements=missing,
            field_statuses={},
        )

    # 1. Legal Name
    if not identity.legal_name or len(identity.legal_name) < 2:
        missing.append(MissingRequirement(
            code="legal_name_missing",
            field="legal_name",
            blocking=True,
            message="Der vollständige rechtliche Name (oder Firmenname) ist erforderlich.",
        ))
        field_statuses["legal_name"] = "missing"
    else:
        field_statuses["legal_name"] = "provided"

    # 2. Address
    if not identity.address or not identity.address.line1 or len(identity.address.line1) < 3:
        missing.append(MissingRequirement(
            code="address_line1_missing",
            field="address.line1",
            blocking=True,
            message="Eine vollständige ladungsfähige Geschäftsanschrift (Straße & Hausnr.) ist erforderlich.",
        ))
        field_statuses["address.line1"] = "missing"
    else:
        field_statuses["address.line1"] = "provided"

    if not identity.address or not identity.address.city or not identity.address.postal_code:
        missing.append(MissingRequirement(
            code="address_city_postal_missing",
            field="address.city",
            blocking=True,
            message="Postleitzahl und Ort der Geschäftsanschrift sind erforderlich.",
        ))
        field_statuses["address.city"] = "missing"
    else:
        field_statuses["address.city"] = "provided"

    if not identity.address or not identity.address.country_code:
        missing.append(MissingRequirement(
            code="address_country_missing",
            field="address.country_code",
            blocking=True,
            message="Das Land der Niederlassung ist erforderlich.",
        ))
        field_statuses["address.country_code"] = "missing"
    else:
        field_statuses["address.country_code"] = "provided"

    # 3. Contact Email
    if not identity.email or not EMAIL_RE.match(identity.email):
        missing.append(MissingRequirement(
            code="email_invalid",
            field="email",
            blocking=True,
            message="Eine gültige geschäftliche Kontakt-E-Mail-Adresse ist erforderlich.",
        ))
        field_statuses["email"] = "invalid"
    else:
        field_statuses["email"] = "provided"

    # 4. Business entity requirements
    if identity.entity_type == EntityType.BUSINESS:
        if not identity.registry_info or not identity.registry_info.registration_number:
            missing.append(MissingRequirement(
                code="business_registration_number_missing",
                field="registry_info.registration_number",
                blocking=True,
                message="Für juristische Personen/Unternehmen ist die Handelsregisternummer erforderlich.",
            ))
            field_statuses["registry_info"] = "missing"
        else:
            field_statuses["registry_info"] = "provided"

        if not identity.legal_representative or len(identity.legal_representative) < 2:
            missing.append(MissingRequirement(
                code="legal_representative_missing",
                field="legal_representative",
                blocking=True,
                message="Die Angabe des Vertretungsberechtigten (z.B. Geschäftsführer) ist erforderlich.",
            ))
            field_statuses["legal_representative"] = "missing"
        else:
            field_statuses["legal_representative"] = "provided"

    # 5. DSA Art. 30 Trader Self-Declaration
    has_active_decl = False
    active_version: str | None = None
    for decl in declarations:
        if decl.legal_text_version == DSA_TRADER_DECLARATION_VERSION and decl.accepted_at:
            has_active_decl = True
            active_version = decl.legal_text_version
            break

    if not has_active_decl:
        missing.append(MissingRequirement(
            code="trader_declaration_missing",
            field="trader_declaration",
            blocking=True,
            message="Die gesetzliche Händler-Selbsterklärung gem. DSA Art. 30 muss akzeptiert werden.",
        ))
        field_statuses["trader_declaration"] = "missing"
    else:
        field_statuses["trader_declaration"] = "accepted"

    # 6. Stripe Connect status check (informative for payouts)
    stripe_payouts_ready = False
    if stripe_profile and stripe_profile.get("payouts_enabled"):
        stripe_payouts_ready = True
        field_statuses["stripe_payout"] = "verified_by_stripe"
    else:
        field_statuses["stripe_payout"] = "not_ready"

    # 7. Check state
    is_suspended = identity.verification_state == VerificationState.SUSPENDED
    is_rejected = identity.verification_state == VerificationState.REJECTED

    if is_suspended:
        return ComplianceEvaluation(
            eligible=False,
            state=VerificationState.SUSPENDED,
            missing_requirements=[MissingRequirement(
                code="provider_suspended",
                field="status",
                blocking=True,
                message=f"Der Betreiber ist derzeit suspendiert: {identity.state_reason or 'Governance Review'}",
            )],
            field_statuses=field_statuses,
            active_declaration_version=active_version,
            stripe_payouts_ready=stripe_payouts_ready,
        )

    if is_rejected:
        return ComplianceEvaluation(
            eligible=False,
            state=VerificationState.REJECTED,
            missing_requirements=[MissingRequirement(
                code="provider_rejected",
                field="status",
                blocking=True,
                message=f"Das Anbieterprofil wurde abgelehnt: {identity.state_reason or 'Validation failure'}",
            )],
            field_statuses=field_statuses,
            active_declaration_version=active_version,
            stripe_payouts_ready=stripe_payouts_ready,
        )

    if missing:
        computed_state = VerificationState.INCOMPLETE
    elif identity.verification_state == VerificationState.REVERIFICATION_REQUIRED:
        computed_state = VerificationState.REVERIFICATION_REQUIRED
    elif identity.verification_state == VerificationState.VERIFIED:
        computed_state = VerificationState.VERIFIED
    else:
        computed_state = VerificationState.PENDING_REVIEW

    eligible = computed_state == VerificationState.VERIFIED and len(missing) == 0

    return ComplianceEvaluation(
        eligible=eligible,
        state=computed_state,
        missing_requirements=missing,
        field_statuses=field_statuses,
        active_declaration_version=active_version,
        stripe_payouts_ready=stripe_payouts_ready,
    )
