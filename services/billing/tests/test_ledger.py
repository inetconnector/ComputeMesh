"""Unit tests for ComputeMesh Double-Entry Billing & Settlement Ledger."""
from pathlib import Path
import tempfile
import unittest

from services.billing.ledger import (
    BillingError,
    DuplicateEventError,
    InsufficientBalanceError,
    Ledger,
    LedgerReconciliationError,
    Posting,
    Transaction,
)


class TestBillingLedger(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_file = Path(self.temp_dir.name) / "ledger_journal.jsonl"
        self.ledger = Ledger(storage_path=self.storage_file)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_deposit_and_balance(self) -> None:
        # Deposit $50.00 (50,000,000 micro-units)
        tx = self.ledger.deposit_customer_credits(
            customer_account_id="cust_001",
            amount_micro_units=50_000_000,
            payment_reference="stripe_pi_123456",
        )
        self.assertIsNotNone(tx.tx_id)
        self.assertEqual(self.ledger.get_balance("cust_001"), 50_000_000)
        self.assertEqual(self.ledger.get_balance("gateway:escrow"), 50_000_000)

    def test_job_execution_metering_and_split(self) -> None:
        # Deposit $20.00
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_001",
            amount_micro_units=20_000_000,
            payment_reference="stripe_pi_001",
        )

        # Execute 5,000 prompt + 5,000 completion tokens on 7B model ($0.20 per 1M -> 200 micro/tok)
        # Total charge = 10,000 * 200 = 2,000,000 micro-units ($2.00)
        # Network operator fee (25%) = 500,000 micro-units ($0.50)
        # Provider pool (75%) = 1,500,000 micro-units ($1.50)
        tx = self.ledger.record_job_execution(
            job_id="job_alpha_1",
            customer_account_id="cust_001",
            provider_shares=[("node_miner_5x8gb", 1.0)],
            model_id="qwen/qwen2.5-7b-instruct",
            prompt_tokens=5_000_000,
            completion_tokens=5_000_000,
        )
        self.assertIsNotNone(tx.tx_id)
        self.assertEqual(self.ledger.get_balance("cust_001"), 18_000_000)  # $18.00 remaining
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 500_000)  # $0.50 operator cut
        self.assertEqual(self.ledger.get_platform_revenue_micro_units(), 500_000)
        self.assertEqual(self.ledger.get_platform_revenue_usd(), 0.50)
        self.assertEqual(self.ledger.get_balance("provider:node_miner_5x8gb"), 1_500_000)  # $1.50

    def test_multi_provider_proportional_split(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_002",
            amount_micro_units=100_000_000,
            payment_reference="stripe_pi_002",
        )

        # Two nodes: Coordinator (30%) + Worker Rig (70%)
        # Model 32B ($0.50 prompt / $0.90 completion = $0.70/1M blended), 10M tokens = 7,000,000 micro-units ($7.00)
        # Operator Network fee 25% = 1,750,000 micro-units ($1.75)
        # Provider pool 75% = 5,250,000 micro-units ($5.25)
        # Node A (30%) = 1,575,000 micro-units ($1.575)
        # Node B (70%) = 3,675,000 micro-units ($3.675)
        self.ledger.record_job_execution(
            job_id="job_multi_1",
            customer_account_id="cust_002",
            provider_shares=[("coord_rtx3080", 0.3), ("worker_rig_5x8gb", 0.7)],
            model_id="qwen/qwen2.5-32b-instruct",
            prompt_tokens=5_000_000,
            completion_tokens=5_000_000,
        )
        self.assertEqual(self.ledger.get_balance("provider:coord_rtx3080"), 1_575_000)
        self.assertEqual(self.ledger.get_balance("provider:worker_rig_5x8gb"), 3_675_000)
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 1_750_000)

    def test_operator_treasury_withdrawal(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_op_test",
            amount_micro_units=50_000_000,
            payment_reference="stripe_op_dep",
        )
        # Run inference job generating $10.00 charge (10,000,000 micro-units) -> $2.50 operator cut
        self.ledger.record_job_execution(
            job_id="job_op_1",
            customer_account_id="cust_op_test",
            provider_shares=[("node_1", 1.0)],
            model_id="llama/llama-3.1-70b-instruct",
            prompt_tokens=5_000_000,
            completion_tokens=2_777_778,
        )
        op_balance = self.ledger.get_platform_revenue_micro_units()
        self.assertGreater(op_balance, 0)
        
        # Withdraw to Operator's Ethereum/Polygon Treasury Wallet
        tx, summary = self.ledger.create_operator_treasury_payout("0xOperatorTreasuryWalletAddress123456789")
        self.assertIsNotNone(tx.tx_id)
        self.assertEqual(summary.wallet_address, "0xOperatorTreasuryWalletAddress123456789")
        self.assertEqual(self.ledger.get_balance("revenue:network_fee"), 0)

    def test_insufficient_balance_fails_closed(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_broke",
            amount_micro_units=100,
            payment_reference="dep_small",
        )
        with self.assertRaises(InsufficientBalanceError):
            self.ledger.record_job_execution(
                job_id="job_oversized",
                customer_account_id="cust_broke",
                provider_shares=[("node_1", 1.0)],
                model_id="qwen/qwen2.5-7b-instruct",
                prompt_tokens=5_000_000,
                completion_tokens=5_000_000,
            )

    def test_idempotent_duplicate_event_prevention(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_003",
            amount_micro_units=10_000_000,
            payment_reference="stripe_pi_dup",
        )
        with self.assertRaises(DuplicateEventError):
            self.ledger.deposit_customer_credits(
                customer_account_id="cust_003",
                amount_micro_units=10_000_000,
                payment_reference="stripe_pi_dup",
            )

    def test_provider_payout_settlement(self) -> None:
        # Deposit $50.00
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_whale",
            amount_micro_units=50_000_000,
            payment_reference="dep_whale",
        )
        # Execute jobs yielding > $25 to provider
        self.ledger.record_job_execution(
            job_id="job_large_1",
            customer_account_id="cust_whale",
            provider_shares=[("miner_node_top", 1.0)],
            model_id="llama/llama-3.1-70b-instruct",
            prompt_tokens=15_000_000,
            completion_tokens=15_000_000,
        )
        provider_bal = self.ledger.get_balance("provider:miner_node_top")
        self.assertGreaterEqual(provider_bal, 25_000_000)

        # Trigger settlement payout
        tx, summary = self.ledger.create_provider_payout(
            provider_node_id="miner_node_top",
            wallet_address="0x71a9f02c4b8e6d0123456789abcdef0123456789",
        )
        self.assertEqual(summary.amount_micro_units, provider_bal)
        self.assertEqual(self.ledger.get_balance("provider:miner_node_top"), 0)

    def test_disk_persistence_and_reload(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_persist",
            amount_micro_units=30_000_000,
            payment_reference="dep_persist",
        )
        self.ledger.record_job_execution(
            job_id="job_persist_1",
            customer_account_id="cust_persist",
            provider_shares=[("node_persist", 1.0)],
            model_id="qwen/qwen2.5-7b-instruct",
            prompt_tokens=10_000_000,
            completion_tokens=10_000_000,
        )

        # Reload new instance from same file
        reloaded = Ledger(storage_path=self.storage_file)
        self.assertEqual(reloaded.get_balance("cust_persist"), self.ledger.get_balance("cust_persist"))
        self.assertEqual(reloaded.get_balance("provider:node_persist"), self.ledger.get_balance("provider:node_persist"))

    def test_full_reconciliation_audit(self) -> None:
        self.ledger.deposit_customer_credits(
            customer_account_id="cust_audit",
            amount_micro_units=50_000_000,
            payment_reference="dep_audit",
        )
        self.ledger.record_job_execution(
            job_id="job_audit_1",
            customer_account_id="cust_audit",
            provider_shares=[("node_a", 0.5), ("node_b", 0.5)],
            model_id="qwen/qwen2.5-7b-instruct",
            prompt_tokens=5000,
            completion_tokens=5000,
        )
        audit = self.ledger.reconcile()
        self.assertEqual(audit["status"], "balanced")
        self.assertEqual(audit["total_transactions"], 2)


if __name__ == "__main__":
    unittest.main()
