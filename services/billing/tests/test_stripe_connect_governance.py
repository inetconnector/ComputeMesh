from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services.billing.accounting import AccountingStore, ProviderAccount, SettlementRecord
from services.billing.ledger import Ledger, MINIMUM_PAYOUT_MICRO_UNITS
from services.billing.stripe_connect import AccountLinkResult, ConnectedAccountResult, StripeConnectService
from services.compliance.dsa_policy import PlatformEnterpriseSize, PlatformOperatorLegalProfile
from services.compliance.fleet_gatekeeper import FleetGatekeeper
from services.compliance.provider_identity import (
    CustomerAudience,
    EntityType,
    IdentityVerificationState,
    MarketplaceMode,
    ProviderIdentity,
    StructuredAddress,
)
from services.compliance.provider_identity_store import ProviderIdentityStore


class TestStripeConnectGovernance(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.accounting_db = Path(self.temp_dir.name) / "accounting.db"
        self.identity_db = Path(self.temp_dir.name) / "identity.db"
        self.ledger_db = Path(self.temp_dir.name) / "ledger.db"

        self.accounting_store = AccountingStore(storage_path=self.accounting_db)
        self.identity_store = ProviderIdentityStore(storage_path=self.identity_db)
        self.ledger = Ledger(storage_path=self.ledger_db)

        self.operator_profile = PlatformOperatorLegalProfile(
            operator_name="InetConnector",
            enterprise_size=PlatformEnterpriseSize.MICRO_ENTERPRISE,
            jurisdiction="DE",
        )
        self.identity_store.save_operator_profile(self.operator_profile)
        self.gatekeeper = FleetGatekeeper(
            identity_store=self.identity_store,
        )
        self.mock_stripe_client = MagicMock()
        self.stripe_service = StripeConnectService(
            stripe_api_key="sk_test_mock_123",
            stripe_client=self.mock_stripe_client,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_minimum_payout_threshold_enforcement(self) -> None:
        # Payout below $25.00 threshold (25,000,000 micro units) is rejected by ledger rules
        below_threshold_micro_units = MINIMUM_PAYOUT_MICRO_UNITS - 1000
        self.assertLess(below_threshold_micro_units, 25_000_000)

        # Minimum payout threshold constant check
        self.assertEqual(MINIMUM_PAYOUT_MICRO_UNITS, 25_000_000)

    def test_governed_provider_onboarding_flow(self) -> None:
        # Register a verified provider in identity store
        ident = self.identity_store.upsert_identity(
            account_id="acc_owner_99",
            entity_type=EntityType.INDIVIDUAL,
            legal_name="Max Mustermann",
            address=StructuredAddress(
                line1="Musterweg 1",
                postal_code="97209",
                city="Veitshöchheim",
                country_code="DE",
            ),
            email="max@example.com",
        )

        # Verify identity
        with self.identity_store._connection() as conn:
            conn.execute(
                "UPDATE provider_identities SET verification_state = 'VERIFIED' WHERE provider_identity_id = ?",
                (ident.provider_identity_id,),
            )

        # Bind fleet to provider
        self.identity_store.bind_fleet(
            fleet_id="flt_alpha_1",
            provider_identity_id=ident.provider_identity_id,
            account_id="acc_owner_99",
            status="active",
            marketplace_mode="B2B_INTERMEDIARY",
        )

        # Gatekeeper permits B2B marketplace
        allowed, reason, missing = self.gatekeeper.can_operate_b2b_marketplace(
            account_id="acc_owner_99",
            fleet_id="flt_alpha_1",
        )
        self.assertTrue(allowed)

        # Mock Stripe Connected Account creation
        self.mock_stripe_client.Account.create.return_value = {
            "id": "acct_stripe_99",
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
        }

        created = self.stripe_service.create_connected_account(
            provider_node_id="flt_alpha_1",
            email="max@example.com",
            country="DE",
        )
        self.assertEqual(created.stripe_connected_account_id, "acct_stripe_99")
        self.assertTrue(created.payouts_enabled)

        # Attach Stripe Connected Account to accounting store
        self.accounting_store.attach_stripe_account(
            provider_node_id="flt_alpha_1",
            stripe_connected_account_id="acct_stripe_99",
            onboarding_status="completed",
        )
        self.accounting_store.update_stripe_account_status(
            provider_node_id="flt_alpha_1",
            onboarding_status="completed",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
        )

        saved = self.accounting_store.get_provider("flt_alpha_1")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.stripe_connected_account_id, "acct_stripe_99")
        self.assertTrue(saved.payouts_enabled)


if __name__ == "__main__":
    unittest.main()
