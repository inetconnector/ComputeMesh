"""DSA Applicability Policy for ComputeMesh Digital Service Architecture.

Evaluates whether Regulation (EU) 2022/2065 (Digital Services Act), in particular
Article 30 (Traceability of Traders) and Article 31 (Compliance by Design), is
applicable to a specific marketplace, cluster, or fleet context.

Considers:
1. Online platform definition (DSA Art. 3(i))
2. Consumer distance contract concluded with traders (DSA Art. 30(1))
3. Marketplace counterparty model (Intermediary vs Reseller)
4. Customer audience (Consumer allowed vs B2B only vs Private members)
5. Micro and Small Enterprise Platform Operator Exemption (DSA Art. 29(1))
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import os
from typing import Any

from .legal_registry import LegalRuleRegistry


class PlatformEnterpriseSize(str, Enum):
    """Enterprise size classification according to EC Recommendation 2003/361/EC and DSA Art. 29."""
    MICRO_ENTERPRISE = "MICRO_ENTERPRISE"        # < 10 headcount, <= 2M EUR turnover/balance sheet
    SMALL_ENTERPRISE = "SMALL_ENTERPRISE"        # < 50 headcount, <= 10M EUR turnover/balance sheet
    NOT_SMALL_ENTERPRISE = "NOT_SMALL_ENTERPRISE" # >= 50 headcount or > 10M EUR turnover/balance sheet
    UNKNOWN = "UNKNOWN"                          # Legal classification pending verification
    VLOP = "VLOP"                                # Very Large Online Platform (>= 45M active EU users)


@dataclass(frozen=True)
class PlatformOperatorLegalProfile:
    """Legal profile of the ComputeMesh platform operator entity for regulatory sizing."""
    operator_name: str = "ComputeMesh Platform Operator"
    enterprise_size: PlatformEnterpriseSize = PlatformEnterpriseSize.UNKNOWN
    jurisdiction: str = "EU/DE"
    evaluated_at: str = ""
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_name": self.operator_name,
            "enterprise_size": self.enterprise_size.value,
            "jurisdiction": self.jurisdiction,
            "evaluated_at": self.evaluated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_environment(cls) -> PlatformOperatorLegalProfile:
        size_raw = os.environ.get("COMPUTEMESH_OPERATOR_ENTERPRISE_SIZE", "").strip().upper()
        size = PlatformEnterpriseSize.UNKNOWN
        if size_raw in PlatformEnterpriseSize.__members__:
            size = PlatformEnterpriseSize[size_raw]

        name = os.environ.get("COMPUTEMESH_OPERATOR_NAME", "").strip() or "ComputeMesh Platform Operator"
        jurisdiction = os.environ.get("COMPUTEMESH_OPERATOR_JURISDICTION", "").strip() or "EU/DE"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        return cls(
            operator_name=name,
            enterprise_size=size,
            jurisdiction=jurisdiction,
            evaluated_at=now,
        )


@dataclass(frozen=True)
class ApplicabilityDecision:
    """Structured and explainable outcome of the DSA applicability evaluation."""
    article_30_applicable: bool
    article_31_applicable: bool
    legal_basis: str
    reasons: list[str] = field(default_factory=list)
    exemptions: list[str] = field(default_factory=list)
    evaluated_at: str = ""
    legal_rule_version: str = "EU_DSA_2026_09"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DSAApplicabilityPolicy:
    """Central decision engine for dynamic DSA applicability across marketplace and cluster modes."""

    LEGAL_RULE_VERSION = "EU_DSA_2026_09"

    def __init__(self, operator_profile: PlatformOperatorLegalProfile | None = None) -> None:
        self.operator_profile = operator_profile or PlatformOperatorLegalProfile.from_environment()

    def evaluate(
        self,
        *,
        marketplace_mode: str,
        counterparty_model: str,
        customer_audience: str,
        provider_entity_type: str = "individual",
    ) -> ApplicabilityDecision:
        """Evaluates DSA Art. 30 / Art. 31 applicability based on the concrete transaction model.
        
        Args:
            marketplace_mode: PUBLIC_INTERMEDIARY, PUBLIC_RESELLER, B2B_INTERMEDIARY, PRIVATE_CLUSTER, ENTERPRISE_PRIVATE
            counterparty_model: CUSTOMER_PROVIDER, CUSTOMER_COMPUTEMESH, DIRECT_PRIVATE_MEMBER
            customer_audience: CONSUMER_ALLOWED, BUSINESS_ONLY, PRIVATE_MEMBERS
            provider_entity_type: individual, business
        """
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        reasons: list[str] = []
        exemptions: list[str] = []

        mode_clean = str(marketplace_mode or "").strip().upper()
        cpty_clean = str(counterparty_model or "").strip().upper()
        aud_clean = str(customer_audience or "").strip().upper()

        # 1. Private / Closed Clusters
        if mode_clean in {"PRIVATE_CLUSTER", "ENTERPRISE_PRIVATE"} or aud_clean == "PRIVATE_MEMBERS":
            reasons.append("closed_private_cluster_no_public_dissemination")
            exemptions.append("dsa_art_3_not_open_to_public")
            return ApplicabilityDecision(
                article_30_applicable=False,
                article_31_applicable=False,
                legal_basis="DSA Art. 3(i) - Closed private infrastructure without public dissemination of trader offerings",
                reasons=reasons,
                exemptions=exemptions,
                evaluated_at=now,
                legal_rule_version=self.LEGAL_RULE_VERSION,
            )

        # 2. Reseller Model (Customer contracts with ComputeMesh directly)
        if cpty_clean == "CUSTOMER_COMPUTEMESH" or mode_clean == "PUBLIC_RESELLER":
            reasons.append("reseller_model_customer_contracts_with_platform")
            exemptions.append("dsa_art_30_no_direct_trader_distance_contract")
            return ApplicabilityDecision(
                article_30_applicable=False,
                article_31_applicable=False,
                legal_basis="DSA Art. 30(1) - Customer concludes contract with platform reseller, provider acts as upstream infrastructure supplier",
                reasons=reasons,
                exemptions=exemptions,
                evaluated_at=now,
                legal_rule_version=self.LEGAL_RULE_VERSION,
            )

        # 3. Pure B2B Marketplace (No consumers allowed)
        if aud_clean == "BUSINESS_ONLY" or mode_clean == "B2B_INTERMEDIARY":
            reasons.append("b2b_only_marketplace")
            exemptions.append("dsa_art_30_no_consumer_distance_contract")
            return ApplicabilityDecision(
                article_30_applicable=False,
                article_31_applicable=False,
                legal_basis="DSA Art. 30(1) - Pure business-to-business marketplace; DSA Art. 30 mandates traceability specifically for distance contracts with consumers",
                reasons=reasons,
                exemptions=exemptions,
                evaluated_at=now,
                legal_rule_version=self.LEGAL_RULE_VERSION,
            )

        # 4. Micro and Small Enterprise Operator Exemption under DSA Art. 29(1)
        op_size = self.operator_profile.enterprise_size
        if op_size in {PlatformEnterpriseSize.MICRO_ENTERPRISE, PlatformEnterpriseSize.SMALL_ENTERPRISE}:
            reasons.append(f"platform_operator_qualifies_as_{op_size.value.lower()}")
            exemptions.append("dsa_art_29_sme_exemption")
            return ApplicabilityDecision(
                article_30_applicable=False,
                article_31_applicable=False,
                legal_basis="DSA Art. 29(1) - Platform operator qualifies as micro or small enterprise under Recommendation 2003/361/EC",
                reasons=reasons,
                exemptions=exemptions,
                evaluated_at=now,
                legal_rule_version=self.LEGAL_RULE_VERSION,
            )

        # 5. Operator size UNKNOWN: Fails safe to legal review requirement
        if op_size == PlatformEnterpriseSize.UNKNOWN:
            reasons.append("platform_operator_enterprise_size_unverified")
            return ApplicabilityDecision(
                article_30_applicable=False,
                article_31_applicable=False,
                legal_basis="LEGAL_REVIEW_REQUIRED: Platform operator enterprise size under DSA Art. 29 is not verified. Fails safe to avoid unlawful PII collection.",
                reasons=reasons,
                exemptions=["operator_size_pending_verification"],
                evaluated_at=now,
                legal_rule_version=self.LEGAL_RULE_VERSION,
            )

        # 6. Non-exempt Public Intermediary Marketplace with Consumers
        if aud_clean == "CONSUMER_ALLOWED" and mode_clean == "PUBLIC_INTERMEDIARY":
            reasons.append("public_intermediary_marketplace_allowing_consumers")
            reasons.append("non_exempt_platform_operator")
            return ApplicabilityDecision(
                article_30_applicable=True,
                article_31_applicable=True,
                legal_basis="DSA Art. 30(1) & Art. 31 - Mandatory trader traceability and compliance by design on consumer-facing digital intermediary platforms",
                reasons=reasons,
                exemptions=[],
                evaluated_at=now,
                legal_rule_version=self.LEGAL_RULE_VERSION,
            )

        # Default fallback
        reasons.append(f"unclassified_combination_mode_{mode_clean}_aud_{aud_clean}")
        return ApplicabilityDecision(
            article_30_applicable=False,
            article_31_applicable=False,
            legal_basis="APPLICABILITY_UNKNOWN - Defaulting to non-enforcement until legal classification is clarified",
            reasons=reasons,
            exemptions=["unclassified_marketplace_mode"],
            evaluated_at=now,
            legal_rule_version=self.LEGAL_RULE_VERSION,
        )
