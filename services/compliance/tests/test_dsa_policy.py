"""Unit tests for DSAApplicabilityPolicy and SME platform operator exemption (Art. 29)."""
from __future__ import annotations

import unittest

from services.compliance.dsa_policy import (
    ApplicabilityDecision,
    DSAApplicabilityPolicy,
    PlatformEnterpriseSize,
    PlatformOperatorLegalProfile,
)
from services.compliance.provider_identity import (
    ContractCounterpartyModel,
    CustomerAudience,
    MarketplaceMode,
)


class DSAApplicabilityPolicyTests(unittest.TestCase):

    def test_b2b_only_marketplace_exempts_dsa_art30(self) -> None:
        """Pure B2B transactions do not involve consumer distance contracts under DSA Art. 30(1)."""
        operator = PlatformOperatorLegalProfile(
            operator_name="Large Intermediary GmbH",
            enterprise_size=PlatformEnterpriseSize.NOT_SMALL_ENTERPRISE,
        )
        policy = DSAApplicabilityPolicy(operator)

        decision = policy.evaluate(
            marketplace_mode=MarketplaceMode.B2B_INTERMEDIARY.value,
            counterparty_model=ContractCounterpartyModel.CUSTOMER_PROVIDER.value,
            customer_audience=CustomerAudience.BUSINESS_ONLY.value,
            provider_entity_type="business",
        )

        self.assertFalse(decision.article_30_applicable)
        self.assertFalse(decision.article_31_applicable)
        self.assertIn("b2b_only_marketplace", decision.reasons)
        self.assertIn("dsa_art_30_no_consumer_distance_contract", decision.exemptions)

    def test_private_cluster_exempts_dsa_art30(self) -> None:
        """Closed private clusters without public dissemination are outside online platform marketplace obligations."""
        policy = DSAApplicabilityPolicy()

        decision = policy.evaluate(
            marketplace_mode=MarketplaceMode.PRIVATE_CLUSTER.value,
            counterparty_model=ContractCounterpartyModel.DIRECT_PRIVATE_MEMBER.value,
            customer_audience=CustomerAudience.PRIVATE_MEMBERS.value,
        )

        self.assertFalse(decision.article_30_applicable)
        self.assertIn("closed_private_cluster_no_public_dissemination", decision.reasons)

    def test_reseller_model_exempts_provider_from_dsa_art30(self) -> None:
        """In a reseller model, customer contracts directly with ComputeMesh, not the provider."""
        operator = PlatformOperatorLegalProfile(
            enterprise_size=PlatformEnterpriseSize.NOT_SMALL_ENTERPRISE,
        )
        policy = DSAApplicabilityPolicy(operator)

        decision = policy.evaluate(
            marketplace_mode=MarketplaceMode.PUBLIC_RESELLER.value,
            counterparty_model=ContractCounterpartyModel.CUSTOMER_COMPUTEMESH.value,
            customer_audience=CustomerAudience.CONSUMER_ALLOWED.value,
        )

        self.assertFalse(decision.article_30_applicable)
        self.assertIn("reseller_model_customer_contracts_with_platform", decision.reasons)

    def test_micro_and_small_enterprise_operator_exempt_under_art29(self) -> None:
        """Under DSA Art. 29(1), micro and small enterprise platforms are exempt from Art. 30 and 31."""
        micro_operator = PlatformOperatorLegalProfile(
            operator_name="Startup Compute UG",
            enterprise_size=PlatformEnterpriseSize.MICRO_ENTERPRISE,
        )
        policy_micro = DSAApplicabilityPolicy(micro_operator)

        decision_micro = policy_micro.evaluate(
            marketplace_mode=MarketplaceMode.PUBLIC_INTERMEDIARY.value,
            counterparty_model=ContractCounterpartyModel.CUSTOMER_PROVIDER.value,
            customer_audience=CustomerAudience.CONSUMER_ALLOWED.value,
        )

        self.assertFalse(decision_micro.article_30_applicable)
        self.assertIn("dsa_art_29_sme_exemption", decision_micro.exemptions)

        small_operator = PlatformOperatorLegalProfile(
            operator_name="Small Tech GmbH",
            enterprise_size=PlatformEnterpriseSize.SMALL_ENTERPRISE,
        )
        policy_small = DSAApplicabilityPolicy(small_operator)

        decision_small = policy_small.evaluate(
            marketplace_mode=MarketplaceMode.PUBLIC_INTERMEDIARY.value,
            counterparty_model=ContractCounterpartyModel.CUSTOMER_PROVIDER.value,
            customer_audience=CustomerAudience.CONSUMER_ALLOWED.value,
        )

        self.assertFalse(decision_small.article_30_applicable)
        self.assertIn("dsa_art_29_sme_exemption", decision_small.exemptions)

    def test_unknown_operator_size_fails_safe_to_legal_review(self) -> None:
        """If operator size is unknown, fails safe rather than unlawfully forcing PII collection."""
        unverified_operator = PlatformOperatorLegalProfile(
            enterprise_size=PlatformEnterpriseSize.UNKNOWN,
        )
        policy = DSAApplicabilityPolicy(unverified_operator)

        decision = policy.evaluate(
            marketplace_mode=MarketplaceMode.PUBLIC_INTERMEDIARY.value,
            counterparty_model=ContractCounterpartyModel.CUSTOMER_PROVIDER.value,
            customer_audience=CustomerAudience.CONSUMER_ALLOWED.value,
        )

        self.assertFalse(decision.article_30_applicable)
        self.assertIn("LEGAL_REVIEW_REQUIRED", decision.legal_basis)

    def test_non_exempt_public_b2c_intermediary_requires_dsa_art30(self) -> None:
        """When a large/non-exempt platform operates a public intermediary marketplace allowing consumers, Art. 30 applies."""
        large_operator = PlatformOperatorLegalProfile(
            operator_name="Global Compute Corp",
            enterprise_size=PlatformEnterpriseSize.NOT_SMALL_ENTERPRISE,
        )
        policy = DSAApplicabilityPolicy(large_operator)

        decision = policy.evaluate(
            marketplace_mode=MarketplaceMode.PUBLIC_INTERMEDIARY.value,
            counterparty_model=ContractCounterpartyModel.CUSTOMER_PROVIDER.value,
            customer_audience=CustomerAudience.CONSUMER_ALLOWED.value,
        )

        self.assertTrue(decision.article_30_applicable)
        self.assertTrue(decision.article_31_applicable)
        self.assertIn("public_intermediary_marketplace_allowing_consumers", decision.reasons)


if __name__ == "__main__":
    unittest.main()
