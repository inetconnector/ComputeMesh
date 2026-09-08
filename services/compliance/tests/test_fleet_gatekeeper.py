from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from services.compliance.dsa_policy import PlatformEnterpriseSize, PlatformOperatorLegalProfile
from services.compliance.fleet_gatekeeper import (
    FleetGatekeeper,
    FleetGatekeeperError,
)
from services.compliance.provider_identity import (
    BusinessRegistryInfo,
    DSA_TRADER_DECLARATION_VERSION,
    EntityType,
    IdentityVerificationState,
    MarketplaceMode,
    StructuredAddress,
    VerificationState,
)
from services.compliance.provider_identity_store import ProviderIdentityStore


class FleetGatekeeperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_gatekeeper.db"
        self.store = ProviderIdentityStore(self.db_path)
        # Configure non-exempt operator profile to test strict public B2C rules
        self.store.save_operator_profile(
            PlatformOperatorLegalProfile(
                operator_name="Global Platform Corp",
                enterprise_size=PlatformEnterpriseSize.NOT_SMALL_ENTERPRISE,
            )
        )
        self.gatekeeper = FleetGatekeeper(self.store)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_can_create_fleet(self) -> None:
        allowed, err, missing = self.gatekeeper.can_create_fleet("facc_user1")
        self.assertTrue(allowed)
        self.assertIsNone(err)

    def test_marketplace_operation_blocked_without_identity(self) -> None:
        allowed, code, missing = self.gatekeeper.can_operate_marketplace("facc_user1", "fleet-1")
        self.assertFalse(allowed)
        self.assertEqual(code, "PROVIDER_IDENTITY_REQUIRED")
        self.assertTrue(len(missing) > 0)

        with self.assertRaises(FleetGatekeeperError) as ctx:
            self.gatekeeper.require_marketplace_eligibility("facc_user1", "fleet-1")
        self.assertEqual(ctx.exception.code, "PROVIDER_IDENTITY_REQUIRED")

    def test_public_b2c_marketplace_blocked_without_declaration(self) -> None:
        addr = StructuredAddress(line1="Hauptstr. 5", city="Hamburg", postal_code="20095", country_code="DE")
        self.store.upsert_identity(
            account_id="facc_user1",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Felix Tester",
            address=addr,
            email="felix@example.com",
        )
        allowed, code, missing = self.gatekeeper.can_operate_marketplace("facc_user1", "fleet-1")
        self.assertFalse(allowed)
        self.assertEqual(code, "TRADER_DECLARATION_REQUIRED")

    def test_private_cluster_operable_without_dsa_declaration(self) -> None:
        """Closed private clusters require verified identity but do NOT mandate DSA Art. 30 self-declaration."""
        addr = StructuredAddress(line1="Hauptstr. 5", city="Hamburg", postal_code="20095", country_code="DE")
        identity = self.store.upsert_identity(
            account_id="facc_user1",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Felix Tester",
            address=addr,
            email="felix@example.com",
        )
        self.store.update_verification_state(
            identity.provider_identity_id,
            IdentityVerificationState.VERIFIED,
            actor="admin",
            reason="Verified for enterprise cluster",
        )

        allowed, code, missing = self.gatekeeper.can_operate_private_cluster("facc_user1", "fleet-private-1")
        self.assertTrue(allowed)
        self.assertIsNone(code)
        self.assertEqual(len(missing), 0)

    def test_public_b2c_allowed_when_verified_with_declaration(self) -> None:
        addr = StructuredAddress(line1="Hauptstr. 5", city="Hamburg", postal_code="20095", country_code="DE")
        identity = self.store.upsert_identity(
            account_id="facc_user1",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Felix Tester",
            address=addr,
            email="felix@example.com",
        )
        self.store.record_declaration(
            provider_identity_id=identity.provider_identity_id,
            account_id="facc_user1",
            legal_text_version=DSA_TRADER_DECLARATION_VERSION,
        )
        self.store.update_verification_state(
            identity.provider_identity_id,
            IdentityVerificationState.VERIFIED,
            actor="admin",
            reason="Verified successfully",
        )

        allowed, code, missing = self.gatekeeper.can_operate_marketplace("facc_user1", "fleet-1")
        self.assertTrue(allowed)
        self.assertIsNone(code)
        self.assertEqual(len(missing), 0)

        # One verified provider can operate multiple fleets
        allowed2, _, _ = self.gatekeeper.can_operate_marketplace("facc_user1", "fleet-2")
        self.assertTrue(allowed2)

    def test_marketplace_operation_blocked_when_suspended(self) -> None:
        addr = StructuredAddress(line1="Hauptstr. 5", city="Hamburg", postal_code="20095", country_code="DE")
        identity = self.store.upsert_identity(
            account_id="facc_user1",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Felix Tester",
            address=addr,
            email="felix@example.com",
        )
        self.store.record_declaration(
            provider_identity_id=identity.provider_identity_id,
            account_id="facc_user1",
            legal_text_version=DSA_TRADER_DECLARATION_VERSION,
        )
        self.store.update_verification_state(
            identity.provider_identity_id,
            IdentityVerificationState.SUSPENDED,
            actor="compliance_team",
            reason="P2B terms violation",
        )

        allowed, code, missing = self.gatekeeper.can_operate_marketplace("facc_user1", "fleet-1")
        self.assertFalse(allowed)
        self.assertEqual(code, "PROVIDER_SUSPENDED")

        # Also blocked for private cluster when suspended
        allowed_priv, code_priv, _ = self.gatekeeper.can_operate_private_cluster("facc_user1", "fleet-1")
        self.assertFalse(allowed_priv)
        self.assertEqual(code_priv, "PROVIDER_SUSPENDED")


if __name__ == "__main__":
    unittest.main()
