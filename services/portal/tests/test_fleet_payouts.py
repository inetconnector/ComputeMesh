"""Comprehensive Unit and Integration Tests for Fleet Payouts & Stripe Connect System."""
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

from services.billing.accounting import AccountingStore, SettlementRecord
from services.billing.ledger import Ledger, MICRO_UNIT_SCALE, MINIMUM_PAYOUT_MICRO_UNITS
from services.billing.owner_credits import owner_bucket_account
from services.billing.owner_settlement import OwnerPayoutProfile, OwnerPayoutProfileStore, PayoutCapableOwnerLedger
from services.billing.stripe_connect import AccountLinkResult, ConnectedAccountResult, StripeConnectService
from services.portal.routes_payouts import PortalPayoutsHandler
from services.portal.server import PortalHandler
from services.portal import passkey_routes
from services.portal.fleet_accounts import FleetAccountStore
import services.gateway.server as gateway_server_module


class TestFleetPayoutsSubsystem(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        self.account_store = AccountingStore(self.tmp_path / "accounting.db")
        self.ledger = PayoutCapableOwnerLedger(self.tmp_path / "ledger.json")

        self.mock_stripe = MagicMock(spec=StripeConnectService)
        self.mock_stripe.stripe_api_key = "sk_test_mock_123"
        self.mock_stripe.connect_api_mode = "v1"
        self.mock_stripe.create_connected_account.return_value = ConnectedAccountResult(
            provider_node_id="owner_test_123",
            stripe_connected_account_id="acct_stripe_mock_123",
            onboarding_status="pending",
            charges_enabled=False,
            payouts_enabled=False,
            details_submitted=False,
        )
        self.mock_stripe.create_account_link.return_value = AccountLinkResult(
            provider_node_id="owner_test_123",
            stripe_connected_account_id="acct_stripe_mock_123",
            onboarding_url="https://connect.stripe.com/setup/s/mock_link_123",
            expires_at=int(time.time()) + 300,
        )
        self.mock_stripe.retrieve_connected_account.return_value = ConnectedAccountResult(
            provider_node_id="owner_test_123",
            stripe_connected_account_id="acct_stripe_mock_123",
            onboarding_status="active",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
        )
        self.mock_stripe.stripe_client = MagicMock()
        self.mock_stripe.stripe_client.Transfer.create.return_value = {
            "id": "tr_mock_stripe_transfer_999",
            "amount": 3000,
            "currency": "usd",
            "destination": "acct_stripe_mock_123",
        }

        self.payouts_handler = PortalPayoutsHandler(
            ledger=self.ledger,
            account_store=self.account_store,
            stripe_connect=self.mock_stripe,
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_payout_overview_initial_state(self) -> None:
        overview = self.payouts_handler.get_payout_overview("owner_test_123")
        self.assertEqual(overview["owner_id"], "owner_test_123")
        self.assertEqual(overview["earned_balance_usd"], 0.0)
        self.assertFalse(overview["payouts_enabled"])
        self.assertFalse(overview["can_withdraw"])
        self.assertEqual(overview["minimum_payout_usd"], 25.0)

    def test_start_onboarding_creates_stripe_account_and_link(self) -> None:
        res = self.payouts_handler.start_onboarding(
            owner_id="owner_test_123",
            email="provider@company.com",
            country="DE",
        )
        self.assertEqual(res["stripe_connected_account_id"], "acct_stripe_mock_123")
        self.assertIn("https://connect.stripe.com", res["onboarding_url"])

        profile = self.payouts_handler.profile_store.get_profile("owner_test_123")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.stripe_connected_account_id, "acct_stripe_mock_123")

    def test_refresh_status_updates_profile(self) -> None:
        self.payouts_handler.profile_store.upsert_profile(
            owner_id="owner_test_123",
            stripe_connected_account_id="acct_stripe_mock_123",
            stripe_onboarding_status="pending",
            payouts_enabled=False,
        )
        updated = self.payouts_handler.refresh_status("owner_test_123")
        self.assertTrue(updated["payouts_enabled"])
        self.assertEqual(updated["stripe_onboarding_status"], "active")

    def test_settlement_rejected_when_payouts_not_enabled(self) -> None:
        # Give $50 earned balance
        earned_account = owner_bucket_account("owner_test_123", "earned")
        self.ledger.credit_owner_earned_credits(
            owner_id="owner_test_123",
            amount_micro_units=50 * MICRO_UNIT_SCALE,
            earning_reference="job_test_01",
        )
        # But payouts_enabled is False
        self.payouts_handler.profile_store.upsert_profile(
            owner_id="owner_test_123",
            stripe_connected_account_id="acct_stripe_mock_123",
            payouts_enabled=False,
        )

        res = self.payouts_handler.execute_settlement("owner_test_123")
        self.assertIn("error", res)
        self.assertIn("payouts_enabled=False", res["error"])

    def test_settlement_rejected_when_below_minimum_threshold(self) -> None:
        # Give $10 earned balance (minimum is $25)
        self.ledger.credit_owner_earned_credits(
            owner_id="owner_test_123",
            amount_micro_units=10 * MICRO_UNIT_SCALE,
            earning_reference="job_test_02",
        )
        self.payouts_handler.profile_store.upsert_profile(
            owner_id="owner_test_123",
            stripe_connected_account_id="acct_stripe_mock_123",
            payouts_enabled=True,
        )

        res = self.payouts_handler.execute_settlement("owner_test_123")
        self.assertIn("error", res)
        self.assertIn("Minimum payout threshold not reached", res["error"])

    def test_settlement_succeeds_when_eligible(self) -> None:
        # Give $30 earned balance
        self.ledger.credit_owner_earned_credits(
            owner_id="owner_test_123",
            amount_micro_units=30 * MICRO_UNIT_SCALE,
            earning_reference="job_test_03",
        )
        self.payouts_handler.profile_store.upsert_profile(
            owner_id="owner_test_123",
            stripe_connected_account_id="acct_stripe_mock_123",
            payouts_enabled=True,
        )

        self.mock_stripe.stripe_client.Transfer.create.return_value = {
            "id": "tr_mock_stripe_transfer_999",
            "amount": 3000,
            "currency": "usd",
            "destination": "acct_stripe_mock_123",
        }

        res = self.payouts_handler.execute_settlement("owner_test_123")
        self.assertFalse(res.get("error"))
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["amount_micro_units"], 30 * MICRO_UNIT_SCALE)
        self.assertEqual(res["stripe_transfer_id"], "tr_mock_stripe_transfer_999")

        # Earned balance should now be 0
        earned_account = owner_bucket_account("owner_test_123", "earned")
        self.assertEqual(self.ledger.get_balance(earned_account), 0)


class TestFleetPayoutsHttpEndpoints(unittest.TestCase):
    PORT = 13025
    BASE = f"http://127.0.0.1:{PORT}"

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.PORT), PortalHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        self.original_fleet_store = passkey_routes.FLEET_ACCOUNT_STORE
        self.fleet_store = FleetAccountStore(self.tmp_path / "fleet.db")
        passkey_routes.FLEET_ACCOUNT_STORE = self.fleet_store

        self.account_store = AccountingStore(self.tmp_path / "accounting.db")
        self.ledger = PayoutCapableOwnerLedger(self.tmp_path / "ledger.json")

        self.mock_stripe = MagicMock(spec=StripeConnectService)
        self.mock_stripe.stripe_api_key = "sk_test_mock_456"
        self.mock_stripe.connect_api_mode = "v1"
        self.mock_stripe.create_connected_account.return_value = ConnectedAccountResult(
            provider_node_id="acct_http_test",
            stripe_connected_account_id="acct_http_stripe_456",
            onboarding_status="pending",
            charges_enabled=False,
            payouts_enabled=False,
            details_submitted=False,
        )
        self.mock_stripe.create_account_link.return_value = AccountLinkResult(
            provider_node_id="acct_http_test",
            stripe_connected_account_id="acct_http_stripe_456",
            onboarding_url="https://connect.stripe.com/setup/s/http_link_456",
            expires_at=int(time.time()) + 300,
        )
        self.mock_stripe.retrieve_connected_account.return_value = ConnectedAccountResult(
            provider_node_id="acct_http_test",
            stripe_connected_account_id="acct_http_stripe_456",
            onboarding_status="active",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
        )
        self.mock_stripe.stripe_client = MagicMock()
        self.mock_stripe.stripe_client.Transfer.create.return_value = {
            "id": "tr_mock_http_transfer_888",
            "amount": 2500,
            "currency": "usd",
            "destination": "acct_http_stripe_456",
        }

        PortalHandler.payouts_handler = PortalPayoutsHandler(
            ledger=self.ledger,
            account_store=self.account_store,
            stripe_connect=self.mock_stripe,
        )

    def tearDown(self) -> None:
        passkey_routes.FLEET_ACCOUNT_STORE = self.original_fleet_store
        self.tmp_dir.cleanup()

    def test_payouts_overview_via_http(self) -> None:
        owner_key = "owk_http_test_key_abc"
        req = urllib.request.Request(
            f"{self.BASE}/api/portal/fleet/payouts?owner_key={owner_key}",
            headers={"X-Owner-Key": owner_key},
        )
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("earned_balance_usd", data)
        self.assertIn("stripe_onboarding_status", data)
        self.assertIn("minimum_payout_usd", data)

    def test_payouts_onboarding_via_http(self) -> None:
        owner_key = "owk_http_test_key_abc"
        req = urllib.request.Request(
            f"{self.BASE}/api/portal/fleet/payouts/onboard",
            data=json.dumps({"owner_key": owner_key, "email": "dev@mesh.com"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-Owner-Key": owner_key},
        )
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("onboarding_url", data)
        self.assertEqual(data["stripe_connected_account_id"], "acct_http_stripe_456")

    def test_payouts_refresh_via_http(self) -> None:
        owner_key = "owk_http_test_key_abc"
        owner_id = gateway_server_module.owner_id_for_key(owner_key)
        # Seed profile
        PortalHandler.payouts_handler.profile_store.upsert_profile(
            owner_id=owner_id,
            stripe_connected_account_id="acct_http_stripe_456",
        )
        req = urllib.request.Request(
            f"{self.BASE}/api/portal/fleet/payouts/refresh",
            data=json.dumps({"owner_key": owner_key}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-Owner-Key": owner_key},
        )
        resp = urllib.request.urlopen(req)
        self.assertEqual(resp.status, HTTPStatus.OK)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(data["payouts_enabled"])


if __name__ == "__main__":
    unittest.main()
