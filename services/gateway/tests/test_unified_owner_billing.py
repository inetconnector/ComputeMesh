"""Gateway tests for the opt-in unified owner credit migration layer."""
from pathlib import Path
import tempfile
import unittest

from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.gateway.auth import GatewayAuthManager, api_credential_id
from services.gateway.routes_billing import BillingRoutesHandler
from services.gateway.teaser import TeaserQuotaManager


class TestUnifiedOwnerBillingGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.ledger = GatewayOwnerCreditLedger(storage_path=root / "ledger.jsonl")
        self.owner_store = OwnerAccountStore(root / "owners.sqlite3")
        self.teaser = TeaserQuotaManager(max_requests=5, max_tokens=1000)
        self.token = "cm_live_unified_owner_alice"
        self.auth = GatewayAuthManager(
            ledger=self.ledger,
            teaser_manager=self.teaser,
            api_keys={self.token: "alice"},
            owner_account_store=self.owner_store,
        )
        self.routes = BillingRoutesHandler(
            ledger=self.ledger,
            stripe_svc=object(),  # balance/topup tests do not invoke Stripe methods
            auth_manager=self.auth,
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_registered_key_binds_to_owner_without_automatic_money_grant(self) -> None:
        result = self.auth.authenticate_request(self.headers)
        self.assertTrue(result.is_authenticated)
        self.assertEqual(result.account_id, "alice")
        self.assertEqual(result.owner_id, "alice")
        self.assertEqual(
            self.owner_store.owner_for_api_credential(api_credential_id(self.token)),
            "alice",
        )
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.total_spendable_micro_units, 0)

    def test_balance_endpoint_exposes_earned_purchased_promo_and_withdrawable(self) -> None:
        self.auth.authenticate_request(self.headers)
        self.ledger.credit_owner_earned_credits(
            owner_id="alice",
            amount_micro_units=7_500_000,
            earning_reference="job-a",
        )
        self.ledger.deposit_owner_purchased_credits(
            owner_id="alice",
            amount_micro_units=20_000_000,
            payment_reference="purchase-a",
        )
        self.ledger.grant_owner_promo_credits(
            owner_id="alice",
            amount_micro_units=25_000_000,
            grant_reference="promo-a",
            policy_version="onboarding-v1",
        )

        payload, error, status = self.routes.handle_get_balance(self.headers)
        self.assertIsNone(error)
        self.assertEqual(int(status), 200)
        assert payload is not None
        self.assertEqual(payload["balance_model"], "unified_owner_v1")
        self.assertEqual(payload["earned_micro_units"], 7_500_000)
        self.assertEqual(payload["purchased_micro_units"], 20_000_000)
        self.assertEqual(payload["promo_micro_units"], 25_000_000)
        self.assertEqual(payload["withdrawable_micro_units"], 7_500_000)
        self.assertEqual(payload["balance_micro_units"], 52_500_000)

    def test_topup_enters_purchased_bucket_not_earned_or_promo(self) -> None:
        payload, error, status = self.routes.handle_post_topup(
            self.headers,
            {"amount_usd": 12.5},
        )
        self.assertIsNone(error)
        self.assertEqual(int(status), 200)
        assert payload is not None
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.purchased_micro_units, 12_500_000)
        self.assertEqual(balances.earned_micro_units, 0)
        self.assertEqual(balances.promo_micro_units, 0)
        self.assertEqual(balances.withdrawable_micro_units, 0)

    def test_legacy_stripe_deposit_surface_routes_owner_money_to_purchased(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="alice",
            amount_micro_units=15_000_000,
            payment_reference="stripe_checkout:cs_test_owner",
        )
        balances = self.ledger.get_owner_balances("alice")
        self.assertEqual(balances.purchased_micro_units, 15_000_000)
        self.assertEqual(self.ledger.get_balance("alice"), 15_000_000)

    def test_teaser_compatibility_does_not_create_owner_purchased_credit(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="teaser_203_0_113_1",
            amount_micro_units=1_000_000,
            payment_reference="teaser-test",
        )
        self.assertEqual(self.ledger.get_balance("teaser_203_0_113_1"), 1_000_000)
        self.assertEqual(
            self.ledger.get_owner_balances("teaser_203_0_113_1").total_spendable_micro_units,
            0,
        )


if __name__ == "__main__":
    unittest.main()
