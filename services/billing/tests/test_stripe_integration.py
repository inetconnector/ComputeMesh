"""Unit tests for Stripe Checkout & Automated Webhook Payment Integration."""
import unittest

from services.billing.ledger import Ledger
from services.billing.stripe_integration import (
    StripeIntegrationError,
    StripePaymentService,
)


class TestStripeIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.stripe_svc = StripePaymentService(ledger=self.ledger)

    def test_checkout_session_creation(self) -> None:
        result = self.stripe_svc.create_checkout_session(
            customer_account_id="cust_stripe_01",
            amount_usd=50.00,
        )
        self.assertTrue(result.session_id.startswith("cs_test_"))
        self.assertIn(result.session_id, result.checkout_url)
        self.assertEqual(result.amount_micro_units, 50_000_000)

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
                    "amount_total": 2500,  # 2500 cents = $25.00
                    "client_reference_id": "cust_stripe_02",
                }
            },
        }
        res = self.stripe_svc.process_webhook_event(payload=webhook_payload)
        self.assertEqual(res["status"], "credited")
        self.assertEqual(res["amount_usd"], 25.00)
        self.assertEqual(self.ledger.get_balance("cust_stripe_02"), 25_000_000)

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
                    "client_reference_id": "cust_stripe_03",
                }
            },
        }
        # First call
        res1 = self.stripe_svc.process_webhook_event(payload=webhook_payload)
        self.assertEqual(res1["status"], "credited")
        self.assertEqual(self.ledger.get_balance("cust_stripe_03"), 10_000_000)

        # Duplicate webhook replay
        res2 = self.stripe_svc.process_webhook_event(payload=webhook_payload)
        self.assertEqual(res2["status"], "already_processed")
        # Balance must remain exactly 10,000,000 without double-crediting
        self.assertEqual(self.ledger.get_balance("cust_stripe_03"), 10_000_000)

    def test_unhandled_event_ignored(self) -> None:
        res = self.stripe_svc.process_webhook_event(payload={"type": "customer.created"})
        self.assertEqual(res["status"], "ignored")

    def test_bounds_rejection(self) -> None:
        with self.assertRaises(StripeIntegrationError):
            self.stripe_svc.create_checkout_session(
                customer_account_id="cust_invalid",
                amount_usd=2.00,  # Below $5.00 min
            )


if __name__ == "__main__":
    unittest.main()
