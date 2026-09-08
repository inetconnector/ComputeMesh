from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from services.compliance.provider_identity import (
    BusinessRegistryInfo,
    DSA_TRADER_DECLARATION_VERSION,
    EntityType,
    EvidenceSource,
    IdentityEvidence,
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

    def test_public_trader_profile_allowlist_does_not_leak_private_data(self) -> None:
        addr = StructuredAddress(
            line1="Private Street 123",
            city="Munich",
            postal_code="80331",
            country_code="DE",
        )
        identity = ProviderIdentity(
            provider_identity_id="prv_test123",
            account_id="facc_user123",
            entity_type=EntityType.BUSINESS,
            legal_name="Mustermann Compute GmbH",
            trade_name="MusterCloud",
            legal_representative="Max Mustermann",
            acting_person_relationship="Geschäftsführer",
            address=addr,
            email="contact@mustercloud.de",
            phone="+491701234567",
            registry_info=BusinessRegistryInfo(
                registry_country="DE",
                registry_name="AG München",
                registration_number="HRB 12345",
            ),
            vat_id="DE123456789",
            verification_state=VerificationState.VERIFIED,
            stripe_account_id="acct_stripe123",
        )

        public = identity.to_public_profile(declaration_accepted=True)
        pub_dict = public.to_dict()

        # Public allowlist checks
        self.assertEqual(pub_dict["trade_or_legal_name"], "MusterCloud")
        self.assertEqual(pub_dict["city"], "Munich")
        self.assertEqual(pub_dict["country_code"], "DE")
        self.assertEqual(pub_dict["contact_email"], "contact@mustercloud.de")
        self.assertTrue(pub_dict["trader_declaration_active"])

        # Private fields strictly excluded
        self.assertNotIn("Private Street 123", json.dumps(pub_dict))
        self.assertNotIn("+491701234567", json.dumps(pub_dict))
        self.assertNotIn("acct_stripe123", json.dumps(pub_dict))
        self.assertNotIn("facc_user123", json.dumps(pub_dict))
        self.assertNotIn("Geschäftsführer", json.dumps(pub_dict))

    def test_evaluate_provider_requirements_individual(self) -> None:
        addr = StructuredAddress(line1="Main St 1", city="Berlin", postal_code="10115", country_code="DE")
        identity = ProviderIdentity(
            provider_identity_id="prv_1",
            account_id="facc_1",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="John Doe",
            address=addr,
            email="john@example.com",
            verification_state=VerificationState.PENDING_REVIEW,
        )

        # Without DSA declaration -> Incomplete
        eval1 = evaluate_provider_requirements(identity, [], [])
        self.assertFalse(eval1.eligible)
        self.assertEqual(eval1.state, VerificationState.INCOMPLETE)
        self.assertTrue(any(r.code == "trader_declaration_missing" for r in eval1.missing_requirements))

        # With active DSA declaration -> Pending Review or Verified
        decl = TraderDeclaration(
            declaration_id="decl_1",
            provider_identity_id="prv_1",
            account_id="facc_1",
            legal_text_version=DSA_TRADER_DECLARATION_VERSION,
            accepted_at="2026-09-08T12:00:00Z",
        )
        eval2 = evaluate_provider_requirements(identity, [decl], [])
        self.assertEqual(len(eval2.missing_requirements), 0)
        self.assertEqual(eval2.state, VerificationState.PENDING_REVIEW)


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
        self.assertEqual(identity.verification_state, VerificationState.PENDING_REVIEW)

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
            VerificationState.VERIFIED,
            actor="admin",
            reason="Approved manually",
        )
        verified = self.store.get_identity(identity.provider_identity_id)
        self.assertEqual(verified.verification_state, VerificationState.VERIFIED)

        # Update non-material field (e.g. trade_name) -> stays VERIFIED
        self.store.upsert_identity(
            account_id="facc_abc",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Anna Schmidt",
            address=addr,
            email="anna@schmidt.de",
            trade_name="Anna Cloud",
        )
        non_material = self.store.get_identity(identity.provider_identity_id)
        self.assertEqual(non_material.verification_state, VerificationState.VERIFIED)

        # Update material field (e.g. legal_name) -> triggers REVERIFICATION_REQUIRED
        self.store.upsert_identity(
            account_id="facc_abc",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Anna Meier",
            address=addr,
            email="anna@schmidt.de",
        )
        material = self.store.get_identity(identity.provider_identity_id)
        self.assertEqual(material.verification_state, VerificationState.REVERIFICATION_REQUIRED)

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
            client_ip="192.168.1.1",
        )
        self.assertEqual(decl.legal_text_version, DSA_TRADER_DECLARATION_VERSION)

        declarations = self.store.list_declarations(identity.provider_identity_id)
        self.assertEqual(len(declarations), 1)

        ev = self.store.add_evidence(
            provider_identity_id=identity.provider_identity_id,
            field_scope="payout_account",
            source=EvidenceSource.STRIPE_CONNECT,
            status="valid",
            evidence_reference="acct_12345",
        )
        self.assertEqual(ev.source, EvidenceSource.STRIPE_CONNECT)

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
        )
        self.assertEqual(binding["fleet_id"], "fleet-berlin-01")
        self.assertEqual(binding["provider_identity_id"], identity.provider_identity_id)

        retrieved = self.store.get_fleet_binding("fleet-berlin-01")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["status"], "active")


if __name__ == "__main__":
    unittest.main()
