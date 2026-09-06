"""Unit Tests for Scheduled Batch Settlement Engine."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from services.billing.accounting import AccountingStore
from services.billing.ledger import MICRO_UNIT_SCALE
from services.billing.owner_credits import owner_bucket_account
from services.billing.owner_settlement import OwnerPayoutProfileStore, PayoutCapableOwnerLedger
from services.billing.scheduled_settlement import run_batch_settlement_cycle
from services.billing.stripe_connect import ConnectedAccountResult, StripeConnectService


class TestScheduledBatchSettlement(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

        self.account_store = AccountingStore(self.tmp_path / "accounting.db")
        self.ledger = PayoutCapableOwnerLedger(self.tmp_path / "ledger.json")
        self.profile_store = OwnerPayoutProfileStore(self.account_store)

        self.mock_stripe = MagicMock(spec=StripeConnectService)
        self.mock_stripe.stripe_api_key = "sk_test_mock_123"
        self.mock_stripe.connect_api_mode = "v1"
        self.mock_stripe.retrieve_connected_account.return_value = ConnectedAccountResult(
            provider_node_id="owner_alpha",
            stripe_connected_account_id="acct_stripe_alpha",
            onboarding_status="active",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
        )
        self.mock_stripe.stripe_client = MagicMock()
        self.mock_stripe.stripe_client.Transfer.create.return_value = {
            "id": "tr_mock_batch_001",
            "amount": 5000,
            "currency": "usd",
            "destination": "acct_stripe_alpha",
        }

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_cycle_skips_when_payouts_not_enabled(self) -> None:
        # Seed owner with $50 but payouts_enabled = False
        self.profile_store.upsert_profile(
            owner_id="owner_alpha",
            stripe_connected_account_id="acct_stripe_alpha",
            payouts_enabled=False,
        )
        self.ledger.credit_owner_earned_credits(
            owner_id="owner_alpha",
            amount_micro_units=50 * MICRO_UNIT_SCALE,
            earning_reference="job_batch_01",
        )

        results = run_batch_settlement_cycle(self.ledger, self.account_store, self.mock_stripe)
        self.assertEqual(len(results), 0)
        # Balance remains untouched
        self.assertEqual(self.ledger.get_balance(owner_bucket_account("owner_alpha", "earned")), 50 * MICRO_UNIT_SCALE)

    def test_cycle_skips_when_below_threshold(self) -> None:
        # Seed owner with $10 (threshold is $25)
        self.profile_store.upsert_profile(
            owner_id="owner_alpha",
            stripe_connected_account_id="acct_stripe_alpha",
            payouts_enabled=True,
            details_submitted=True,
        )
        self.ledger.credit_owner_earned_credits(
            owner_id="owner_alpha",
            amount_micro_units=10 * MICRO_UNIT_SCALE,
            earning_reference="job_batch_02",
        )

        results = run_batch_settlement_cycle(self.ledger, self.account_store, self.mock_stripe)
        self.assertEqual(len(results), 0)
        self.assertEqual(self.ledger.get_balance(owner_bucket_account("owner_alpha", "earned")), 10 * MICRO_UNIT_SCALE)

    def test_cycle_settles_eligible_owner(self) -> None:
        # Seed owner with $50 and payouts_enabled = True
        self.profile_store.upsert_profile(
            owner_id="owner_alpha",
            stripe_connected_account_id="acct_stripe_alpha",
            payouts_enabled=True,
            details_submitted=True,
        )
        self.ledger.credit_owner_earned_credits(
            owner_id="owner_alpha",
            amount_micro_units=50 * MICRO_UNIT_SCALE,
            earning_reference="job_batch_03",
        )

        results = run_batch_settlement_cycle(self.ledger, self.account_store, self.mock_stripe)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[0]["amount_micro_units"], 50 * MICRO_UNIT_SCALE)
        self.assertEqual(results[0]["stripe_transfer_id"], "tr_mock_batch_001")

        # Balance is now settled (0)
        self.assertEqual(self.ledger.get_balance(owner_bucket_account("owner_alpha", "earned")), 0)


if __name__ == "__main__":
    unittest.main()
