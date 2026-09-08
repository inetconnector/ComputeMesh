"""Domain models and context-aware requirement evaluation for ComputeMesh Provider and Trader Identities.

Complies with:
- Regulation (EU) 2022/2065 (Digital Services Act, Art. 3, 29, 30 & 31)
- Regulation (EU) 2016/679 (GDPR, Art. 5, 6, 13/14, 25, 32 - Privacy by Design & Data Minimization)
- Regulation (EU) 2019/1150 (P2B Regulation - Transparent suspension and operational terms)
- Directive (EU) 2021/514 (DAC7 Scope Evaluation)

Key Architectural Principles:
1. Strict domain separation: Account -> ProviderIdentity -> Fleets -> Stripe Connect.
2. ProviderIdentity is a general platform entity decoupled from generic DSA KYC.
3. DSA Art. 30 applies ONLY when evaluated as legally applicable by DSAApplicabilityPolicy.
4. Separate orthogonal state dimensions (Identity, Payment, Marketplace, DSA, Fleet, Tax).
5. Field-level verification evidence with provenance and freshness tracking.
6. Dynamic public disclosure: MinimalProviderPublicProfile vs. DSAArticle30PublicDisclosure.
7. Natural person privacy: Private residential addresses & personal phones are protected from public disclosure.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .dsa_policy import ApplicabilityDecision, DSAApplicabilityPolicy, PlatformOperatorLegalProfile
from .legal_registry import LegalRuleRegistry

DSA_TRADER_DECLARATION_VERSION = "dsa_art30_v1.0"
ISO_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EntityType(str, Enum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class MarketplaceMode(str, Enum):
    PUBLIC_INTERMEDIARY = "PUBLIC_INTERMEDIARY"  # Customer ↔ Provider (ComputeMesh acts as intermediary)
    PUBLIC_RESELLER = "PUBLIC_RESELLER"          # Customer ↔ ComputeMesh (Provider is upstream supplier)
    B2B_INTERMEDIARY = "B2B_INTERMEDIARY"        # Business Customer ↔ Provider (Pure B2B)
    PRIVATE_CLUSTER = "PRIVATE_CLUSTER"          # Closed cluster / Private members only
    ENTERPRISE_PRIVATE = "ENTERPRISE_PRIVATE"    # Dedicated enterprise nodes


class ContractCounterpartyModel(str, Enum):
    CUSTOMER_PROVIDER = "CUSTOMER_PROVIDER"      # Distance contract between end customer and provider
    CUSTOMER_COMPUTEMESH = "CUSTOMER_COMPUTEMESH"# Contract between end customer and ComputeMesh reseller
    DIRECT_PRIVATE_MEMBER = "DIRECT_PRIVATE_MEMBER"# Internal / intra-cluster allocation


class CustomerAudience(str, Enum):
    CONSUMER_ALLOWED = "CONSUMER_ALLOWED"        # B2C & B2B (Consumers permitted)
    BUSINESS_ONLY = "BUSINESS_ONLY"              # Pure B2B (Commercial entities only)
    PRIVATE_MEMBERS = "PRIVATE_MEMBERS"          # Designated private group members


class IdentityVerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    INCOMPLETE = "INCOMPLETE"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REVERIFICATION_REQUIRED = "REVERIFICATION_REQUIRED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


# Backward compatibility alias
VerificationState = IdentityVerificationState


class PaymentVerificationState(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    PENDING_STRIPE = "PENDING_STRIPE"
    PAYOUTS_ENABLED = "PAYOUTS_ENABLED"
    RESTRICTED = "RESTRICTED"


class MarketplaceEligibilityState(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    PRIVATE_CLUSTER_ONLY = "PRIVATE_CLUSTER_ONLY"
    B2B_ELIGIBLE = "B2B_ELIGIBLE"
    PUBLIC_MARKETPLACE_ELIGIBLE = "PUBLIC_MARKETPLACE_ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class DSATraderComplianceState(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_DECLARATION = "PENDING_DECLARATION"
    COMPLIANT = "COMPLIANT"
    EXEMPT_ART29 = "EXEMPT_ART29"
    NON_COMPLIANT = "NON_COMPLIANT"


class FleetGovernanceState(str, Enum):
    UNGOVERNED = "UNGOVERNED"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    BLOCKED = "BLOCKED"


class TaxProfileState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    SELF_DECLARED = "SELF_DECLARED"
    VAT_CONFIRMED = "VAT_CONFIRMED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EvidenceSource(str, Enum):
    SELF_ATTESTATION = "SELF_ATTESTATION"
    STRIPE_CONNECT = "STRIPE_CONNECT"
    COMMERCIAL_REGISTER = "COMMERCIAL_REGISTER"
    VAT_VIES = "VAT_VIES"
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    PHONE_VERIFICATION = "PHONE_VERIFICATION"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    EUDI_WALLET = "EUDI_WALLET"


class EvidenceConfidence(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"
    REGISTER_CONFIRMED = "REGISTER_CONFIRMED"
    PSP_VERIFIED = "PSP_VERIFIED"


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
    confidence: EvidenceConfidence = EvidenceConfidence.SELF_REPORTED
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
            "confidence": self.confidence.value if isinstance(self.confidence, EvidenceConfidence) else str(self.confidence),
            "evidence_reference": self.evidence_reference,
            "verification_method": self.verification_method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IdentityEvidence:
        source_val = data.get("source")
        source = EvidenceSource(source_val) if isinstance(source_val, str) and source_val in EvidenceSource.__members__ else EvidenceSource.SELF_ATTESTATION
        conf_val = data.get("confidence")
        confidence = EvidenceConfidence(conf_val) if isinstance(conf_val, str) and conf_val in EvidenceConfidence.__members__ else EvidenceConfidence.SELF_REPORTED
        return cls(
            evidence_id=str(data.get("evidence_id", "")),
            provider_identity_id=str(data.get("provider_identity_id", "")),
            field_scope=str(data.get("field_scope", "")),
            source=source,
            status=str(data.get("status", "valid")),
            verified_at=str(data.get("verified_at", "")),
            verification_method=str(data.get("verification_method", "")),
            confidence=confidence,
            evidence_reference=str(data.get("evidence_reference", "")),
            expires_at=data.get("expires_at"),
        )

    def is_valid(self, now_iso: str | None = None) -> bool:
        if self.status != "valid":
            return False
        if self.expires_at:
            current = now_iso or utc_now()
            if self.expires_at < current:
                return False
        return True


@dataclass(frozen=True)
class LegalDeclaration:
    """Generic versioned legal declaration record."""
    declaration_id: str
    provider_identity_id: str
    account_id: str
    declaration_type: str  # e.g. DSA_ART30_TRADER_COMMITMENT, B2B_PROVIDER_TERMS, DPA_ATTRIBUTES
    version: str
    accepted_at: str
    text_hash: str = ""
    locale: str = "de"
    applicability_context: str = "PUBLIC_MARKETPLACE"
    audit_reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalDeclaration:
        return cls(
            declaration_id=str(data.get("declaration_id", "")),
            provider_identity_id=str(data.get("provider_identity_id", "")),
            account_id=str(data.get("account_id", "")),
            declaration_type=str(data.get("declaration_type", "DSA_ART30_TRADER_COMMITMENT")),
            version=str(data.get("version", data.get("legal_text_version", DSA_TRADER_DECLARATION_VERSION))),
            accepted_at=str(data.get("accepted_at", "")),
            text_hash=str(data.get("text_hash", data.get("ip_hash", ""))),
            locale=str(data.get("locale", "de")),
            applicability_context=str(data.get("applicability_context", "PUBLIC_MARKETPLACE")),
            audit_reference=str(data.get("audit_reference", "")),
        )


# Backward-compatible alias
TraderDeclaration = LegalDeclaration


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
    identity_state: IdentityVerificationState = IdentityVerificationState.UNVERIFIED
    state_reason: str | None = None
    stripe_account_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    verified_at: str | None = None
    schema_version: int = 1

    @property
    def verification_state(self) -> IdentityVerificationState:
        """Backward-compatible property alias."""
        return self.identity_state

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
            "identity_state": self.identity_state.value if isinstance(self.identity_state, IdentityVerificationState) else str(self.identity_state),
            "verification_state": self.identity_state.value if isinstance(self.identity_state, IdentityVerificationState) else str(self.identity_state),
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
        entity_type = EntityType(entity_type_raw) if isinstance(entity_type_raw, str) and entity_type_raw in EntityType.__members__ else EntityType.INDIVIDUAL
        state_raw = data.get("identity_state") or data.get("verification_state")
        identity_state = IdentityVerificationState(state_raw) if isinstance(state_raw, str) and state_raw in IdentityVerificationState.__members__ else IdentityVerificationState.UNVERIFIED

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
            identity_state=identity_state,
            state_reason=str(data["state_reason"]) if data.get("state_reason") else None,
            stripe_account_id=str(data["stripe_account_id"]).strip() if data.get("stripe_account_id") else None,
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            verified_at=str(data["verified_at"]) if data.get("verified_at") else None,
            schema_version=int(data.get("schema_version", 1)),
        )

    def to_minimal_public_profile(self) -> MinimalProviderPublicProfile:
        """Standard public profile for operations, private clusters, and B2B."""
        public_name = self.trade_name or (self.legal_name if self.entity_type == EntityType.BUSINESS else f"Provider {self.provider_identity_id[-6:]}")
        return MinimalProviderPublicProfile(
            provider_identity_id=self.provider_identity_id,
            trade_or_legal_name=public_name,
            country_code=self.address.country_code,
            verification_status=self.identity_state.value,
        )

    def to_dsa_public_disclosure(self, *, declaration_accepted: bool = True) -> DSAArticle30PublicDisclosure:
        """Public DSA Art. 30 & 31 disclosure generated ONLY when Art. 30 applies."""
        public_name = self.trade_name or self.legal_name
        # For natural persons: address line1 is protected unless registered as business premises
        postal_address = {
            "city": self.address.city,
            "postal_code": self.address.postal_code,
            "country_code": self.address.country_code,
        }
        if self.entity_type == EntityType.BUSINESS:
            postal_address["line1"] = self.address.line1
            if self.address.line2:
                postal_address["line2"] = self.address.line2

        return DSAArticle30PublicDisclosure(
            provider_identity_id=self.provider_identity_id,
            entity_type=self.entity_type.value,
            trade_or_legal_name=public_name,
            postal_address_public=postal_address,
            contact_email=self.email,
            contact_phone_public=self.phone if self.entity_type == EntityType.BUSINESS else None,
            business_registry=self.registry_info.to_dict() if self.registry_info else None,
            vat_id=self.vat_id,
            dsa_declaration_active=declaration_accepted,
            dsa_declaration_version=DSA_TRADER_DECLARATION_VERSION,
            verification_status=self.identity_state.value,
        )

    def to_public_profile(self, *, declaration_accepted: bool = True, dsa_applicable: bool = False) -> Any:
        """Dynamic serializer selecting the appropriate disclosure DTO."""
        if dsa_applicable:
            return self.to_dsa_public_disclosure(declaration_accepted=declaration_accepted)
        return self.to_minimal_public_profile()


@dataclass(frozen=True)
class MinimalProviderPublicProfile:
    """Minimal privacy-preserving operational public profile."""
    provider_identity_id: str
    trade_or_legal_name: str
    country_code: str
    verification_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DSAArticle30PublicDisclosure:
    """Strictly filtered public transparency disclosure under DSA Art. 30(7)."""
    provider_identity_id: str
    entity_type: str
    trade_or_legal_name: str
    postal_address_public: dict[str, str]
    contact_email: str
    verification_status: str
    dsa_declaration_active: bool
    dsa_declaration_version: str
    contact_phone_public: str | None = None
    business_registry: dict[str, str] | None = None
    vat_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Backward compatibility alias
PublicTraderProfile = DSAArticle30PublicDisclosure


@dataclass(frozen=True)
class MissingRequirement:
    code: str
    field: str
    blocking: bool
    message: str
    legal_basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComplianceEvaluation:
    eligible: bool
    identity_state: IdentityVerificationState
    payment_state: PaymentVerificationState
    marketplace_state: MarketplaceEligibilityState
    dsa_state: DSATraderComplianceState
    fleet_state: FleetGovernanceState
    tax_state: TaxProfileState
    applicability_decision: ApplicabilityDecision
    missing_requirements: list[MissingRequirement] = field(default_factory=list)
    field_statuses: dict[str, str] = field(default_factory=dict)
    active_declaration_version: str | None = None
    stripe_payouts_ready: bool = False

    @property
    def state(self) -> IdentityVerificationState:
        """Backward-compatible state alias."""
        return self.identity_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "state": self.identity_state.value,
            "identity_state": self.identity_state.value,
            "payment_state": self.payment_state.value,
            "marketplace_state": self.marketplace_state.value,
            "dsa_state": self.dsa_state.value,
            "fleet_state": self.fleet_state.value,
            "tax_state": self.tax_state.value,
            "applicability": self.applicability_decision.to_dict(),
            "missing_requirements": [r.to_dict() for r in self.missing_requirements],
            "field_statuses": self.field_statuses,
            "active_declaration_version": self.active_declaration_version,
            "stripe_payouts_ready": self.stripe_payouts_ready,
        }


def evaluate_provider_requirements(
    identity: ProviderIdentity | None,
    declarations: list[LegalDeclaration],
    evidence_list: list[IdentityEvidence],
    stripe_profile: dict[str, Any] | None = None,
    *,
    marketplace_mode: MarketplaceMode | str = MarketplaceMode.PUBLIC_INTERMEDIARY,
    counterparty_model: ContractCounterpartyModel | str = ContractCounterpartyModel.CUSTOMER_PROVIDER,
    customer_audience: CustomerAudience | str = CustomerAudience.CONSUMER_ALLOWED,
    operator_profile: PlatformOperatorLegalProfile | None = None,
) -> ComplianceEvaluation:
    """Evaluates multi-dimensional provider requirements fail-closed against the active context."""
    mode_str = marketplace_mode.value if isinstance(marketplace_mode, MarketplaceMode) else str(marketplace_mode)
    cpty_str = counterparty_model.value if isinstance(counterparty_model, ContractCounterpartyModel) else str(counterparty_model)
    aud_str = customer_audience.value if isinstance(customer_audience, CustomerAudience) else str(customer_audience)

    # 1. Evaluate dynamic DSA applicability
    dsa_policy = DSAApplicabilityPolicy(operator_profile)
    entity_type_str = identity.entity_type.value if identity else "individual"
    applicability = dsa_policy.evaluate(
        marketplace_mode=mode_str,
        counterparty_model=cpty_str,
        customer_audience=aud_str,
        provider_entity_type=entity_type_str,
    )

    missing: list[MissingRequirement] = []
    field_statuses: dict[str, str] = {}

    if identity is None:
        missing.append(MissingRequirement(
            code="provider_identity_missing",
            field="identity",
            blocking=True,
            message="Ein rechtliches Anbieterprofil (Betreiberidentität) muss angelegt werden.",
            legal_basis="GDPR Art. 6(1)(b) - Contractual onboarding",
        ))
        return ComplianceEvaluation(
            eligible=False,
            identity_state=IdentityVerificationState.UNVERIFIED,
            payment_state=PaymentVerificationState.UNCONFIGURED,
            marketplace_state=MarketplaceEligibilityState.NOT_ELIGIBLE,
            dsa_state=DSATraderComplianceState.NOT_APPLICABLE if not applicability.article_30_applicable else DSATraderComplianceState.NON_COMPLIANT,
            fleet_state=FleetGovernanceState.UNGOVERNED,
            tax_state=TaxProfileState.NOT_REQUIRED,
            applicability_decision=applicability,
            missing_requirements=missing,
            field_statuses={},
        )

    # Evidence lookup helper
    valid_evidence_fields = {
        e.field_scope: e for e in evidence_list if e.is_valid()
    }

    # 2. Legal Name validation
    if not identity.legal_name or len(identity.legal_name) < 2:
        missing.append(MissingRequirement(
            code="legal_name_missing",
            field="legal_name",
            blocking=True,
            message="Der vollständige rechtliche Name (oder Firmenname) ist erforderlich.",
            legal_basis="GDPR Art. 6(1)(b)",
        ))
        field_statuses["legal_name"] = "missing"
    else:
        field_statuses["legal_name"] = "provided"
        if "legal_name" in valid_evidence_fields:
            field_statuses["legal_name"] = "verified"

    # 3. Address validation
    if not identity.address or not identity.address.line1 or len(identity.address.line1) < 3:
        missing.append(MissingRequirement(
            code="address_line1_missing",
            field="address.line1",
            blocking=True,
            message="Eine vollständige ladungsfähige Geschäftsanschrift (Straße & Hausnr.) ist erforderlich.",
            legal_basis="GDPR Art. 6(1)(b)",
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
            legal_basis="GDPR Art. 6(1)(b)",
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
            legal_basis="GDPR Art. 6(1)(b)",
        ))
        field_statuses["address.country_code"] = "missing"
    else:
        field_statuses["address.country_code"] = "provided"

    # 4. Contact Email
    if not identity.email or not EMAIL_RE.match(identity.email):
        missing.append(MissingRequirement(
            code="email_invalid",
            field="email",
            blocking=True,
            message="Eine gültige geschäftliche Kontakt-E-Mail-Adresse ist erforderlich.",
            legal_basis="GDPR Art. 6(1)(b)",
        ))
        field_statuses["email"] = "invalid"
    else:
        field_statuses["email"] = "provided"

    # 5. Business Entity specific fields
    if identity.entity_type == EntityType.BUSINESS:
        if not identity.registry_info or not identity.registry_info.registration_number:
            missing.append(MissingRequirement(
                code="business_registration_number_missing",
                field="registry_info.registration_number",
                blocking=True,
                message="Für juristische Personen/Unternehmen ist die Handelsregisternummer erforderlich.",
                legal_basis="GDPR Art. 6(1)(b)" if not applicability.article_30_applicable else "DSA Art. 30(1)(a)",
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
                legal_basis="GDPR Art. 6(1)(b)",
            ))
            field_statuses["legal_representative"] = "missing"
        else:
            field_statuses["legal_representative"] = "provided"

    # 6. DSA Art. 30 Trader Self-Declaration (Enforced ONLY if Art. 30 applies)
    has_active_decl = False
    active_version: str | None = None
    for decl in declarations:
        if decl.declaration_type in {"DSA_ART30_TRADER_COMMITMENT", "dsa_art30"} or decl.version == DSA_TRADER_DECLARATION_VERSION:
            if decl.accepted_at:
                has_active_decl = True
                active_version = decl.version
                break

    if applicability.article_30_applicable:
        if not has_active_decl:
            missing.append(MissingRequirement(
                code="trader_declaration_missing",
                field="trader_declaration",
                blocking=True,
                message="Die gesetzliche Händler-Selbsterklärung gem. DSA Art. 30 Abs. 1 lit. e muss akzeptiert werden.",
                legal_basis="DSA Art. 30(1)(e)",
            ))
            field_statuses["trader_declaration"] = "missing"
            dsa_state = DSATraderComplianceState.PENDING_DECLARATION
        else:
            field_statuses["trader_declaration"] = "accepted"
            dsa_state = DSATraderComplianceState.COMPLIANT
    else:
        field_statuses["trader_declaration"] = "not_required"
        if "dsa_art_29_sme_exemption" in applicability.exemptions:
            dsa_state = DSATraderComplianceState.EXEMPT_ART29
        else:
            dsa_state = DSATraderComplianceState.NOT_APPLICABLE

    # 7. Stripe Connect Payout State
    stripe_payouts_ready = False
    if stripe_profile and stripe_profile.get("payouts_enabled"):
        stripe_payouts_ready = True
        payment_state = PaymentVerificationState.PAYOUTS_ENABLED
        field_statuses["stripe_payout"] = "verified_by_stripe"
    elif identity.stripe_account_id:
        payment_state = PaymentVerificationState.PENDING_STRIPE
        field_statuses["stripe_payout"] = "pending"
    else:
        payment_state = PaymentVerificationState.UNCONFIGURED
        field_statuses["stripe_payout"] = "unconfigured"

    # 8. Tax State
    if identity.vat_id:
        tax_state = TaxProfileState.SELF_DECLARED
    else:
        tax_state = TaxProfileState.NOT_REQUIRED

    # 9. Suspension / Rejection overrides
    if identity.identity_state == IdentityVerificationState.SUSPENDED:
        return ComplianceEvaluation(
            eligible=False,
            identity_state=IdentityVerificationState.SUSPENDED,
            payment_state=payment_state,
            marketplace_state=MarketplaceEligibilityState.SUSPENDED,
            dsa_state=dsa_state,
            fleet_state=FleetGovernanceState.BLOCKED,
            tax_state=tax_state,
            applicability_decision=applicability,
            missing_requirements=[MissingRequirement(
                code="provider_suspended",
                field="status",
                blocking=True,
                message=f"Der Betreiber ist derzeit suspendiert: {identity.state_reason or 'Governance Review'}",
                legal_basis="P2B Art. 4 / Platform Terms",
            )],
            field_statuses=field_statuses,
            active_declaration_version=active_version,
            stripe_payouts_ready=stripe_payouts_ready,
        )

    if identity.identity_state == IdentityVerificationState.REJECTED:
        return ComplianceEvaluation(
            eligible=False,
            identity_state=IdentityVerificationState.REJECTED,
            payment_state=payment_state,
            marketplace_state=MarketplaceEligibilityState.NOT_ELIGIBLE,
            dsa_state=dsa_state,
            fleet_state=FleetGovernanceState.BLOCKED,
            tax_state=tax_state,
            applicability_decision=applicability,
            missing_requirements=[MissingRequirement(
                code="provider_rejected",
                field="status",
                blocking=True,
                message=f"Das Anbieterprofil wurde abgelehnt: {identity.state_reason or 'Validation failure'}",
                legal_basis="P2B Art. 4 / Platform Terms",
            )],
            field_statuses=field_statuses,
            active_declaration_version=active_version,
            stripe_payouts_ready=stripe_payouts_ready,
        )

    # 10. Compute Identity State
    if missing:
        computed_identity_state = IdentityVerificationState.INCOMPLETE
    elif identity.identity_state == IdentityVerificationState.REVERIFICATION_REQUIRED:
        computed_identity_state = IdentityVerificationState.REVERIFICATION_REQUIRED
    elif identity.identity_state == IdentityVerificationState.VERIFIED:
        computed_identity_state = IdentityVerificationState.VERIFIED
    else:
        computed_identity_state = IdentityVerificationState.PENDING_REVIEW

    # 11. Compute Marketplace Eligibility State
    if computed_identity_state == IdentityVerificationState.VERIFIED and len(missing) == 0:
        if mode_str in {"PRIVATE_CLUSTER", "ENTERPRISE_PRIVATE"}:
            marketplace_state = MarketplaceEligibilityState.PRIVATE_CLUSTER_ONLY
        elif mode_str == "B2B_INTERMEDIARY" or aud_str == "BUSINESS_ONLY":
            marketplace_state = MarketplaceEligibilityState.B2B_ELIGIBLE
        else:
            marketplace_state = MarketplaceEligibilityState.PUBLIC_MARKETPLACE_ELIGIBLE
        eligible = True
    else:
        marketplace_state = MarketplaceEligibilityState.NOT_ELIGIBLE
        eligible = False

    fleet_state = FleetGovernanceState.ACTIVE if eligible else FleetGovernanceState.UNGOVERNED

    return ComplianceEvaluation(
        eligible=eligible,
        identity_state=computed_identity_state,
        payment_state=payment_state,
        marketplace_state=marketplace_state,
        dsa_state=dsa_state,
        fleet_state=fleet_state,
        tax_state=tax_state,
        applicability_decision=applicability,
        missing_requirements=missing,
        field_statuses=field_statuses,
        active_declaration_version=active_version,
        stripe_payouts_ready=stripe_payouts_ready,
    )
