"""Tests for durable provider accounts, webhook inbox, and Stripe Connect settlements."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from services.billing.accounting import AccountingStore
from services.billing.ledger import Ledger
from services.billing.stripe_connect import SettlementExecutor, StripeConnectService
from services.billing.stripe_integration import StripePaymentService


class FakeAccountAPI:
    def __init__(self) -> None:
        self.created = []
        self.accounts = {}

    def create(self, **params):
        self.created.append(params)
        account = {
            "id": f"acct_test_{len(self.created):03d}",
            "charges_enabled": False,
            "payouts_enabled": False,
            "details_submitted": False,
        }
        self.accounts[account["id"]] = account
        return account

    def retrieve(self, account_id):
        return self.accounts[account_id]


class FakeAccountLinkAPI:
    def create(self, **params):
        return {
            "url": f"https://connect.stripe.com/setup/e/{params['account']}",
            "expires_at": 1893456000,
        }


class FakeTransferAPI:
    def __init__(self) -> None:
        self.created = []

    def create(self, **params):
        self.created.append(params)
        return {"id": f"tr_test_{len(self.created):03d}"}


class FakeStripeClient:
    def __init__(self) -> None:
        self.Account = FakeAccountAPI()
        self.AccountLink = FakeAccountLinkAPI()
        self.Transfer = FakeTransferAPI()


class FakeV2StripeConnectService(StripeConnectService):
    def __init__(self) -> None:
        super().__init__(stripe_api_key="sk_test_v2", stripe_client=FakeStripeClient())
        self.connect_api_mode = "v2"
        self.requests = []
        self.transfer_status = "restricted"

    def _stripe_v2_request(self, method, path, *, payload=None):
        self.requests.append((method, path, payload))
        if method == "POST" and path == "/v2/core/accounts":
            return {
                "id": "acct_v2_test_001",
                "configuration": {
                    "recipient": {
                        "capabilities": {
                            "stripe_balance": {
                                "stripe_transfers": {
                                    "requested": True,
                                    "status": self.transfer_status,
                                }
                            }
                        }
                    }
                },
            }
        if method == "POST" and path == "/v2/core/account_links":
            return {
                "url": f"https://connect.stripe.com/setup/e/{payload['account']}",
                "expires_at": "2026-08-24T12:00:00Z",
            }
        if method == "GET" and path.startswith("/v2/core/accounts/acct_v2_test_001"):
            return {
                "id": "acct_v2_test_001",
                "configuration": {
                    "recipient": {
                        "capabilities": {
                            "stripe_balance": {
                                "stripe_transfers": {
                                    "requested": True,
                                    "status": self.transfer_status,
                                }
                            }
                        }
                    }
                },
            }
        raise AssertionError(f"unexpected Stripe v2 request: {method} {path}")


class TestAccountingAndSettlement(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.account_store = AccountingStore(Path(self.tempdir.name) / "accounting.sqlite")
        self.ledger = Ledger(storage_path=Path(self.tempdir.name) / "ledger.jsonl")
        self.fake_stripe = FakeStripeClient()
        self.stripe_connect = StripeConnectService(
            stripe_api_key="sk_test_settlement",
            stripe_client=self.fake_stripe,
        )
        self.executor = SettlementExecutor(
            ledger=self.ledger,
            account_store=self.account_store,
            stripe_connect=self.stripe_connect,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_provider_registration_and_connect_onboarding_link(self) -> None:
        provider = self.executor.create_or_refresh_provider_connect_account(
            provider_node_id="node_settle_01",
            display_name="Test Rig",
            payout_wallet_address="0x0000000000000000000000000000000000000001",
            email="provider@example.test",
            country="DE",
        )
        self.assertEqual(provider.ledger_account_id, "provider:node_settle_01")
        self.assertTrue(provider.stripe_connected_account_id.startswith("acct_test_"))
        self.assertEqual(provider.stripe_onboarding_status, "needs_onboarding")
        self.assertEqual(self.fake_stripe.Account.created[0]["capabilities"]["transfers"]["requested"], True)

        link = self.executor.create_provider_onboarding_link(
            provider_node_id="node_settle_01",
            refresh_url="https://example.test/refresh",
            return_url="https://example.test/return",
        )
        self.assertIn(provider.stripe_connected_account_id, link.onboarding_url)

    def test_accounts_v2_provider_registration_and_connect_onboarding_link(self) -> None:
        stripe_connect = FakeV2StripeConnectService()
        executor = SettlementExecutor(
            ledger=self.ledger,
            account_store=self.account_store,
            stripe_connect=stripe_connect,
        )

        provider = executor.create_or_refresh_provider_connect_account(
            provider_node_id="node_settle_v2",
            display_name="Test Rig V2",
            email="provider-v2@example.test",
            country="DE",
        )
        self.assertEqual(provider.stripe_connected_account_id, "acct_v2_test_001")
        self.assertEqual(provider.stripe_onboarding_status, "needs_onboarding")
        account_payload = stripe_connect.requests[0][2]
        self.assertEqual(stripe_connect.requests[0][0:2], ("POST", "/v2/core/accounts"))
        self.assertEqual(account_payload["dashboard"], "express")
        self.assertEqual(account_payload["identity"]["country"], "de")
        self.assertEqual(
            account_payload["configuration"]["recipient"]["capabilities"]["stripe_balance"]["stripe_transfers"]["requested"],
            True,
        )

        link = executor.create_provider_onboarding_link(
            provider_node_id="node_settle_v2",
            refresh_url="https://example.test/refresh",
            return_url="https://example.test/return",
        )
        self.assertIn("acct_v2_test_001", link.onboarding_url)
        self.assertEqual(link.expires_at, "2026-08-24T12:00:00Z")

    def test_accounts_v2_refresh_marks_provider_ready(self) -> None:
        stripe_connect = FakeV2StripeConnectService()
        provider = self.account_store.upsert_provider(provider_node_id="node_settle_v2_ready")
        self.account_store.attach_stripe_account(
            provider_node_id=provider.provider_node_id,
            stripe_connected_account_id="acct_v2_test_001",
        )
        executor = SettlementExecutor(
            ledger=self.ledger,
            account_store=self.account_store,
            stripe_connect=stripe_connect,
        )

        stripe_connect.transfer_status = "active"
        refreshed = executor.refresh_provider_connect_status(provider_node_id=provider.provider_node_id)

        self.assertEqual(refreshed.stripe_onboarding_status, "ready")
        self.assertTrue(refreshed.payouts_enabled)
        self.assertTrue(refreshed.details_submitted)

    def test_webhook_event_inbox_marks_processed_and_blocks_duplicates(self) -> None:
        payload = {"id": "evt_test_001", "type": "checkout.session.completed"}
        first = self.account_store.begin_webhook_event(
            event_id="evt_test_001",
            event_type="checkout.session.completed",
            payload=payload,
        )
        self.assertEqual(first, "new")
        self.account_store.mark_webhook_processed("evt_test_001")
        duplicate = self.account_store.begin_webhook_event(
            event_id="evt_test_001",
            event_type="checkout.session.completed",
            payload=payload,
        )
        self.assertEqual(duplicate, "already_processed")

    def test_account_updated_webhook_refreshes_provider_status(self) -> None:
        self.account_store.upsert_provider(provider_node_id="node_connect_webhook")
        self.account_store.attach_stripe_account(
            provider_node_id="node_connect_webhook",
            stripe_connected_account_id="acct_connect_webhook",
        )
        svc = StripePaymentService(
            ledger=self.ledger,
            webhook_secret="whsec_test",
            stripe_api_key="sk_test_123",
            session_store=None,
            webhook_event_store=self.account_store,
            stripe_client=self.fake_stripe,
            webhook_verifier=lambda raw, sig, sec: __import__("json").loads(raw.decode("utf-8")),
            require_live_configuration=False,
        )
        result = svc.process_webhook_payload(
            raw_payload=(
                b'{"id":"evt_account_updated_001","type":"account.updated","data":{"object":{'
                b'"id":"acct_connect_webhook","charges_enabled":true,"payouts_enabled":true,'
                b'"details_submitted":true,"metadata":{"provider_node_id":"node_connect_webhook"}}}}'
            ),
            signature_header="t=123,v1=testsig",
        )
        provider = self.account_store.get_provider("node_connect_webhook")
        self.assertEqual(result["status"], "updated")
        self.assertEqual(provider.stripe_onboarding_status, "ready")
        self.assertTrue(provider.payouts_enabled)

    def test_accounts_v2_requirements_webhook_refreshes_provider_status(self) -> None:
        self.account_store.upsert_provider(provider_node_id="node_connect_v2_webhook")
        self.account_store.attach_stripe_account(
            provider_node_id="node_connect_v2_webhook",
            stripe_connected_account_id="acct_connect_v2_webhook",
        )
        svc = StripePaymentService(
            ledger=self.ledger,
            webhook_secret="whsec_test",
            stripe_api_key="sk_test_123",
            session_store=None,
            webhook_event_store=self.account_store,
            stripe_client=self.fake_stripe,
            webhook_verifier=lambda raw, sig, sec: __import__("json").loads(raw.decode("utf-8")),
            require_live_configuration=False,
        )

        result = svc.process_webhook_payload(
            raw_payload=(
                b'{"id":"evt_account_v2_requirements_001","type":"v2.core.account[requirements].updated",'
                b'"data":{"object":{"id":"acct_connect_v2_webhook","metadata":{'
                b'"provider_node_id":"node_connect_v2_webhook"},"configuration":{"recipient":{'
                b'"capabilities":{"stripe_balance":{"stripe_transfers":{"requested":true,'
                b'"status":"active"}}}}}}}}'
            ),
            signature_header="t=123,v1=testsig",
        )

        provider = self.account_store.get_provider("node_connect_v2_webhook")
        self.assertEqual(result["status"], "updated")
        self.assertEqual(provider.stripe_onboarding_status, "ready")
        self.assertTrue(provider.payouts_enabled)
        self.assertTrue(provider.details_submitted)

    def test_accounts_v2_thin_webhook_retrieves_account_before_status_refresh(self) -> None:
        self.account_store.upsert_provider(provider_node_id="node_connect_v2_thin_webhook")
        self.account_store.attach_stripe_account(
            provider_node_id="node_connect_v2_thin_webhook",
            stripe_connected_account_id="acct_connect_v2_thin_webhook",
        )
        svc = StripePaymentService(
            ledger=self.ledger,
            webhook_secret="whsec_test",
            stripe_api_key="sk_test_123",
            session_store=None,
            webhook_event_store=self.account_store,
            stripe_client=self.fake_stripe,
            webhook_verifier=lambda raw, sig, sec: __import__("json").loads(raw.decode("utf-8")),
            require_live_configuration=False,
        )
        svc._retrieve_accounts_v2_account = lambda account_id: {
            "id": account_id,
            "metadata": {"provider_node_id": "node_connect_v2_thin_webhook"},
            "configuration": {
                "recipient": {
                    "capabilities": {
                        "stripe_balance": {
                            "stripe_transfers": {
                                "requested": True,
                                "status": "active",
                            }
                        }
                    }
                }
            },
        }

        result = svc.process_webhook_payload(
            raw_payload=(
                b'{"id":"evt_account_v2_thin_001","type":"v2.core.account[requirements].updated",'
                b'"data":{"object":{"id":"acct_connect_v2_thin_webhook"}}}'
            ),
            signature_header="t=123,v1=testsig",
        )

        provider = self.account_store.get_provider("node_connect_v2_thin_webhook")
        self.assertEqual(result["status"], "updated")
        self.assertEqual(provider.stripe_onboarding_status, "ready")
        self.assertTrue(provider.payouts_enabled)

    def test_provider_settlement_transfers_and_drains_payable(self) -> None:
        provider = self.account_store.upsert_provider(provider_node_id="node_ready")
        self.account_store.attach_stripe_account(
            provider_node_id=provider.provider_node_id,
            stripe_connected_account_id="acct_ready_001",
        )
        self.account_store.update_stripe_account_status(
            provider_node_id=provider.provider_node_id,
            onboarding_status="ready",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
        )
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_settle",
            amount_micro_units=50_000_000,
            payment_reference="dep_settle",
        )
        self.ledger.record_job_execution(
            job_id="job_settle",
            customer_account_id="cust_settle",
            provider_shares=[("node_ready", 1.0)],
            model_id="llama/llama-3.1-70b-instruct",
            prompt_tokens=15000,
            completion_tokens=15000,
        )

        payable = self.ledger.get_balance("provider:node_ready")
        self.assertGreaterEqual(payable, 25_000_000)
        settlement = self.executor.run_provider_settlement(provider_node_id="node_ready")
        self.assertEqual(settlement.status, "completed")
        self.assertEqual(settlement.currency, "usd")
        self.assertEqual(settlement.amount_micro_units, payable)
        self.assertEqual(settlement.stripe_transfer_id, "tr_test_001")
        self.assertEqual(self.fake_stripe.Transfer.created[0]["destination"], "acct_ready_001")
        self.assertEqual(self.fake_stripe.Transfer.created[0]["idempotency_key"], f"computemesh:{settlement.settlement_id}")
        self.assertEqual(self.ledger.get_balance("provider:node_ready"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")

    def test_provider_settlement_uses_configured_stripe_currency(self) -> None:
        provider = self.account_store.upsert_provider(provider_node_id="node_ready_eur")
        self.account_store.attach_stripe_account(
            provider_node_id=provider.provider_node_id,
            stripe_connected_account_id="acct_ready_eur",
        )
        self.account_store.update_stripe_account_status(
            provider_node_id=provider.provider_node_id,
            onboarding_status="ready",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
        )
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_settle_eur",
            amount_micro_units=50_000_000,
            payment_reference="dep_settle_eur",
        )
        self.ledger.record_job_execution(
            job_id="job_settle_eur",
            customer_account_id="cust_settle_eur",
            provider_shares=[("node_ready_eur", 1.0)],
            model_id="llama/llama-3.1-70b-instruct",
            prompt_tokens=15000,
            completion_tokens=15000,
        )

        with patch.dict(os.environ, {"COMPUTEMESH_STRIPE_SETTLEMENT_CURRENCY": "eur"}):
            settlement = self.executor.run_provider_settlement(provider_node_id="node_ready_eur")

        self.assertEqual(settlement.status, "completed")
        self.assertEqual(settlement.currency, "eur")
        self.assertEqual(self.fake_stripe.Transfer.created[0]["currency"], "eur")


if __name__ == "__main__":
    unittest.main()
