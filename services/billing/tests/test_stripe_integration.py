"""Unit tests for Stripe Checkout and signed webhook payment integration."""
import json
from pathlib import Path
import tempfile
import unittest

from services.billing.ledger import Ledger
from services.billing.stripe_integration import (
    StripeIntegrationError,
    StripePaymentService,
    StripeSessionStore,
)


class FakeCheckoutSessionAPI:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **params):
        self.calls.append(params)
        return {
            "id": "cs_test_real_api_shape_001",
            "url": "https://checkout.stripe.com/c/pay/cs_test_real_api_shape_001",
            "customer": "cus_test_001",
            "payment_intent": "pi_test_001",
            "livemode": False,
        }


class FakeStripeClient:
    def __init__(self) -> None:
        self.checkout_session_api = FakeCheckoutSessionAPI()
        self.checkout = type("Checkout", (), {})()
        self.checkout.Session = self.checkout_session_api


def trusted_json_verifier(raw_payload: bytes, signature_header: str, endpoint_secret: str):
    if signature_header != "t=123,v1=testsig":
        raise ValueError("invalid test signature")
    if endpoint_secret != "whsec_test":
        raise ValueError("invalid endpoint secret")
    return json.loads(raw_payload.decode("utf-8"))


class FakeStripeResource:
    def __init__(self, payload):
        self.payload = payload

    def to_dict_recursive(self):
        return self.payload


def trusted_sdk_object_verifier(raw_payload: bytes, signature_header: str, endpoint_secret: str):
    return FakeStripeResource(trusted_json_verifier(raw_payload, signature_header, endpoint_secret))


class TestStripeIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = StripeSessionStore(Path(self.tempdir.name) / "stripe_sessions.json")
        self.fake_stripe = FakeStripeClient()
        self.stripe_svc = StripePaymentService(
            ledger=self.ledger,
            webhook_secret="whsec_test",
            stripe_api_key="sk_test_123",
            session_store=self.store,
            stripe_client=self.fake_stripe,
            webhook_verifier=trusted_json_verifier,
            require_live_configuration=True,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_checkout_session_creation(self) -> None:
        result = self.stripe_svc.create_checkout_session(
            customer_account_id="cust_stripe_01",
            amount_usd=50.00,
        )
        self.assertEqual(result.session_id, "cs_test_real_api_shape_001")
        self.assertIn(result.session_id, result.checkout_url)
        self.assertEqual(result.amount_micro_units, 50_000_000)

        call = self.fake_stripe.checkout_session_api.calls[0]
        self.assertEqual(call["mode"], "payment")
        self.assertEqual(call["client_reference_id"], "cust_stripe_01")
        self.assertEqual(call["metadata"]["customer_account_id"], "cust_stripe_01")
        self.assertEqual(call["line_items"][0]["price_data"]["unit_amount"], 5000)
        self.assertEqual(self.store.get(result.session_id).payment_intent_id, "pi_test_001")

    def test_unconfigured_checkout_fails_closed(self) -> None:
        svc = StripePaymentService(ledger=self.ledger)
        with self.assertRaises(StripeIntegrationError):
            svc.create_checkout_session(customer_account_id="cust_unconfigured", amount_usd=25.00)

    def test_checkout_can_be_configured_before_webhook_secret(self) -> None:
        svc = StripePaymentService(
            ledger=self.ledger,
            stripe_api_key="sk_test_checkout_only",
            session_store=self.store,
            stripe_client=self.fake_stripe,
            require_live_configuration=True,
        )
        session = svc.create_checkout_session(customer_account_id="cust_checkout_only", amount_usd=25.00)
        self.assertEqual(session.session_id, "cs_test_real_api_shape_001")
        with self.assertRaises(StripeIntegrationError):
            svc.process_webhook_payload(
                raw_payload=json.dumps({"type": "customer.created"}).encode("utf-8"),
                signature_header="t=123,v1=testsig",
            )

    def test_webhook_successful_deposit(self) -> None:
        sess = self.stripe_svc.create_checkout_session(
            customer_account_id="cust_stripe_02",
            amount_usd=25.00,
        )
        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sess.session_id,
                    "amount_total": 2500,
                    "currency": "usd",
                    "payment_status": "paid",
                    "client_reference_id": "cust_stripe_02",
                    "customer": "cus_test_002",
                    "payment_intent": "pi_test_002",
                }
            },
        }
        res = self.stripe_svc.process_webhook_payload(
            raw_payload=json.dumps(webhook_payload).encode("utf-8"),
            signature_header="t=123,v1=testsig",
        )
        self.assertEqual(res["status"], "credited")
        self.assertEqual(res["amount_usd"], 25.00)
        self.assertEqual(self.ledger.get_balance("cust_stripe_02"), 25_000_000)
        self.assertEqual(self.store.get(sess.session_id).credited_transaction_id, res["transaction_id"])

    def test_duplicate_webhook_is_idempotent(self) -> None:
        sess = self.stripe_svc.create_checkout_session(
            customer_account_id="cust_stripe_03",
            amount_usd=10.00,
        )
        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sess.session_id,
                    "amount_total": 1000,
                    "currency": "usd",
                    "payment_status": "paid",
                    "client_reference_id": "cust_stripe_03",
                }
            },
        }
        raw = json.dumps(webhook_payload).encode("utf-8")
        res1 = self.stripe_svc.process_webhook_payload(raw_payload=raw, signature_header="t=123,v1=testsig")
        self.assertEqual(res1["status"], "credited")
        self.assertEqual(self.ledger.get_balance("cust_stripe_03"), 10_000_000)

        res2 = self.stripe_svc.process_webhook_payload(raw_payload=raw, signature_header="t=123,v1=testsig")
        self.assertEqual(res2["status"], "already_processed")
        self.assertEqual(self.ledger.get_balance("cust_stripe_03"), 10_000_000)

    def test_webhook_accepts_stripe_sdk_event_object(self) -> None:
        svc = StripePaymentService(
            ledger=self.ledger,
            webhook_secret="whsec_test",
            stripe_api_key="sk_test_123",
            session_store=self.store,
            stripe_client=self.fake_stripe,
            webhook_verifier=trusted_sdk_object_verifier,
            require_live_configuration=True,
        )
        sess = svc.create_checkout_session(customer_account_id="cust_stripe_sdk_object", amount_usd=5.00)
        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sess.session_id,
                    "amount_total": 500,
                    "currency": "usd",
                    "payment_status": "paid",
                    "client_reference_id": "cust_stripe_sdk_object",
                }
            },
        }
        res = svc.process_webhook_payload(
            raw_payload=json.dumps(webhook_payload).encode("utf-8"),
            signature_header="t=123,v1=testsig",
        )
        self.assertEqual(res["status"], "credited")
        self.assertEqual(self.ledger.get_balance("cust_stripe_sdk_object"), 5_000_000)

    def test_webhook_credits_purchased_amount_not_tax_gross_total(self) -> None:
        sess = self.stripe_svc.create_checkout_session(customer_account_id="cust_stripe_tax", amount_usd=5.00)
        webhook_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sess.session_id,
                    "amount_subtotal": 500,
                    "amount_total": 595,
                    "currency": "usd",
                    "payment_status": "paid",
                    "client_reference_id": "cust_stripe_tax",
                    "metadata": {"customer_account_id": "cust_stripe_tax", "amount_micro_units": "5000000"},
                }
            },
        }
        res = self.stripe_svc.process_webhook_payload(
            raw_payload=json.dumps(webhook_payload).encode("utf-8"),
            signature_header="t=123,v1=testsig",
        )
        self.assertEqual(res["status"], "credited")
        self.assertEqual(res["amount_usd"], 5.00)
        self.assertEqual(self.ledger.get_balance("cust_stripe_tax"), 5_000_000)

    def test_unhandled_event_ignored(self) -> None:
        payload = {"type": "customer.created"}
        res = self.stripe_svc.process_webhook_payload(
            raw_payload=json.dumps(payload).encode("utf-8"),
            signature_header="t=123,v1=testsig",
        )
        self.assertEqual(res["status"], "ignored")

    def test_direct_untrusted_event_rejected(self) -> None:
        with self.assertRaises(StripeIntegrationError):
            self.stripe_svc.process_webhook_event(payload={"type": "customer.created"})

    def test_invalid_signature_rejected(self) -> None:
        with self.assertRaises(StripeIntegrationError):
            self.stripe_svc.process_webhook_payload(
                raw_payload=json.dumps({"type": "customer.created"}).encode("utf-8"),
                signature_header="t=123,v1=wrong",
            )

    def test_bounds_rejection(self) -> None:
        with self.assertRaises(StripeIntegrationError):
            self.stripe_svc.create_checkout_session(
                customer_account_id="cust_invalid",
                amount_usd=2.00,
            )


if __name__ == "__main__":
    unittest.main()
