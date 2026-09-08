from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from services.compliance.dsa_policy import PlatformEnterpriseSize, PlatformOperatorLegalProfile
from services.compliance.provider_identity import (
    BusinessRegistryInfo,
    ContractCounterpartyModel,
    CustomerAudience,
    DSA_TRADER_DECLARATION_VERSION,
    DSAArticle30PublicDisclosure,
    EntityType,
    EvidenceConfidence,
    EvidenceSource,
    IdentityEvidence,
    IdentityVerificationState,
    LegalDeclaration,
    MarketplaceEligibilityState,
    MarketplaceMode,
    MinimalProviderPublicProfile,
    PaymentVerificationState,
    ProviderIdentity,
    StructuredAddress,
    TraderDeclaration,
    VerificationState,
    evaluate_provider_requirements,
)
from services.compliance.provider_identity_store import (
    ProviderIdentityStore,
    ProviderIdentityStoreError,
)


class ProviderIdentityModelTests(unittest.TestCase):
    def test_structured_address_validation(self) -> None:
        addr = StructuredAddress(
            line1=" Musterstr. 42 ",
            line2=" Hinterhaus ",
            postal_code=" 10115 ",
            city=" Berlin ",
            country_code="de",
        )
        self.assertEqual(addr.line1, "Musterstr. 42")
        self.assertEqual(addr.line2, "Hinterhaus")
        self.assertEqual(addr.postal_code, "10115")
        self.assertEqual(addr.city, "Berlin")
        self.assertEqual(addr.country_code, "DE")

        with self.assertRaises(ValueError):
            StructuredAddress(line1="A", postal_code="1", city="B", country_code="INVALID")

    def test_business_registry_info_validation(self) -> None:
        reg = BusinessRegistryInfo(
            registry_country="de",
            registry_name="Amtsgericht Charlottenburg",
            registration_number="HRB 998877 B",
        )
        self.assertEqual(reg.registry_country, "DE")
        self.assertEqual(reg.registry_name, "Amtsgericht Charlottenburg")
        self.assertEqual(reg.registration_number, "HRB 998877 B")

    def test_minimal_public_profile_preserves_natural_person_privacy(self) -> None:
        """In minimal public profile mode, private address and phone are never exposed."""
        addr = StructuredAddress(
            line1="Private Street 123",
            city="Munich",
            postal_code="80331",
            country_code="DE",
        )
        identity = ProviderIdentity(
            provider_identity_id="prv_individual1",
            account_id="facc_user1",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Max Mustermann",
            address=addr,
            email="max@example.com",
            phone="+491701234567",
            identity_state=IdentityVerificationState.VERIFIED,
        )

        public = identity.to_minimal_public_profile()
        pub_dict = public.to_dict()

        self.assertEqual(pub_dict["country_code"], "DE")
        self.assertNotIn("Private Street 123", json.dumps(pub_dict))
        self.assertNotIn("+491701234567", json.dumps(pub_dict))
        self.assertNotIn("max@example.com", json.dumps(pub_dict))

    def test_dsa_public_disclosure_allowlist(self) -> None:
        """DSA Art. 30 public disclosure outputs only statutory fields."""
        addr = StructuredAddress(
            line1="Private Street 123",
            city="Munich",
            postal_code="80331",
            country_code="DE",
        )
        identity = ProviderIdentity(
            provider_identity_id="prv_biz1",
            account_id="facc_biz1",
            entity_type=EntityType.BUSINESS,
            legal_name="Mustermann Compute GmbH",
            trade_name="MusterCloud",
            legal_representative="Max Mustermann",
            address=addr,
            email="contact@mustercloud.de",
            phone="+4989123456",
            registry_info=BusinessRegistryInfo(
                registry_country="DE",
                registry_name="AG München",
                registration_number="HRB 12345",
            ),
            vat_id="DE123456789",
            identity_state=IdentityVerificationState.VERIFIED,
            stripe_account_id="acct_stripe123",
        )

        public = identity.to_dsa_public_disclosure(declaration_accepted=True)
        pub_dict = public.to_dict()

        self.assertEqual(pub_dict["trade_or_legal_name"], "MusterCloud")
        self.assertEqual(pub_dict["postal_address_public"]["city"], "Munich")
        self.assertEqual(pub_dict["contact_email"], "contact@mustercloud.de")
        self.assertTrue(pub_dict["dsa_declaration_active"])

        # Stripe ID and internal account ID are strictly private
        self.assertNotIn("acct_stripe123", json.dumps(pub_dict))
        self.assertNotIn("facc_biz1", json.dumps(pub_dict))

    def test_state_separation_in_evaluation(self) -> None:
        """Identity verified does not imply Stripe payouts enabled or DSA applicability."""
        addr = StructuredAddress(line1="Main St 1", city="Berlin", postal_code="10115", country_code="DE")
        identity = ProviderIdentity(
            provider_identity_id="prv_1",
            account_id="facc_1",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="John Doe",
            address=addr,
            email="john@example.com",
            identity_state=IdentityVerificationState.VERIFIED,
        )

        # In B2B mode: DSA is not applicable, stripe is unconfigured, identity is verified
        evaluation = evaluate_provider_requirements(
            identity,
            [],
            [],
            marketplace_mode=MarketplaceMode.B2B_INTERMEDIARY,
            customer_audience=CustomerAudience.BUSINESS_ONLY,
        )

        self.assertTrue(evaluation.eligible)
        self.assertEqual(evaluation.identity_state, IdentityVerificationState.VERIFIED)
        self.assertEqual(evaluation.payment_state, PaymentVerificationState.UNCONFIGURED)
        self.assertEqual(evaluation.marketplace_state, MarketplaceEligibilityState.B2B_ELIGIBLE)
        self.assertFalse(evaluation.applicability_decision.article_30_applicable)


class ProviderIdentityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_provider.db"
        self.store = ProviderIdentityStore(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_upsert_and_retrieve_identity(self) -> None:
        addr = StructuredAddress(line1="Torstr. 1", city="Berlin", postal_code="10119", country_code="DE")
        identity = self.store.upsert_identity(
            account_id="facc_abc",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Anna Schmidt",
            address=addr,
            email="anna@schmidt.de",
        )
        self.assertTrue(identity.provider_identity_id.startswith("prv_"))
        self.assertEqual(identity.legal_name, "Anna Schmidt")
        self.assertEqual(identity.identity_state, IdentityVerificationState.PENDING_REVIEW)

        fetched = self.store.get_identity_by_account("facc_abc")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.provider_identity_id, identity.provider_identity_id)

    def test_material_change_invalidates_verified_status(self) -> None:
        addr = StructuredAddress(line1="Torstr. 1", city="Berlin", postal_code="10119", country_code="DE")
        identity = self.store.upsert_identity(
            account_id="facc_abc",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Anna Schmidt",
            address=addr,
            email="anna@schmidt.de",
        )
        self.store.update_verification_state(
            identity.provider_identity_id,
            IdentityVerificationState.VERIFIED,
            actor="admin",
            reason="Approved manually",
        )
        verified = self.store.get_identity(identity.provider_identity_id)
        self.assertEqual(verified.identity_state, IdentityVerificationState.VERIFIED)

        # Update material field (e.g. legal_name) -> triggers REVERIFICATION_REQUIRED
        self.store.upsert_identity(
            account_id="facc_abc",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Anna Meier",
            address=addr,
            email="anna@schmidt.de",
        )
        material = self.store.get_identity(identity.provider_identity_id)
        self.assertEqual(material.identity_state, IdentityVerificationState.REVERIFICATION_REQUIRED)

    def test_declaration_and_evidence_recording(self) -> None:
        addr = StructuredAddress(line1="Torstr. 1", city="Berlin", postal_code="10119", country_code="DE")
        identity = self.store.upsert_identity(
            account_id="facc_abc",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Anna Schmidt",
            address=addr,
            email="anna@schmidt.de",
        )
        decl = self.store.record_declaration(
            provider_identity_id=identity.provider_identity_id,
            account_id="facc_abc",
            legal_text_version=DSA_TRADER_DECLARATION_VERSION,
            declaration_type="DSA_ART30_TRADER_COMMITMENT",
            client_ip="192.168.1.1",
        )
        self.assertEqual(decl.version, DSA_TRADER_DECLARATION_VERSION)

        declarations = self.store.list_declarations(identity.provider_identity_id)
        self.assertEqual(len(declarations), 1)

        ev = self.store.add_evidence(
            provider_identity_id=identity.provider_identity_id,
            field_scope="legal_name",
            source=EvidenceSource.COMMERCIAL_REGISTER,
            status="valid",
            confidence=EvidenceConfidence.REGISTER_CONFIRMED,
            evidence_reference="HRB 12345",
        )
        self.assertEqual(ev.source, EvidenceSource.COMMERCIAL_REGISTER)
        self.assertEqual(ev.confidence, EvidenceConfidence.REGISTER_CONFIRMED)

        evidence_list = self.store.list_evidence(identity.provider_identity_id)
        self.assertEqual(len(evidence_list), 1)

    def test_fleet_provider_binding(self) -> None:
        addr = StructuredAddress(line1="Torstr. 1", city="Berlin", postal_code="10119", country_code="DE")
        identity = self.store.upsert_identity(
            account_id="facc_abc",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Anna Schmidt",
            address=addr,
            email="anna@schmidt.de",
        )
        binding = self.store.bind_fleet(
            fleet_id="fleet-berlin-01",
            provider_identity_id=identity.provider_identity_id,
            account_id="facc_abc",
            status="active",
            marketplace_mode=MarketplaceMode.B2B_INTERMEDIARY,
        )
        self.assertEqual(binding["fleet_id"], "fleet-berlin-01")
        self.assertEqual(binding["marketplace_mode"], "B2B_INTERMEDIARY")

        retrieved = self.store.get_fleet_binding("fleet-berlin-01")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["status"], "active")


if __name__ == "__main__":
    unittest.main()
