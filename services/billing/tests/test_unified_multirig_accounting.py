"""Integration tests for Unified Owner Account Credits & Multi-Rig Ledger.

Validates the full lifecycle:
1. Multi-rig ownership aggregation (multiple rigs earn into one owner).
2. Circular compute economy: Earn on GPU -> Spend on API -> Balance reaches 0 -> Fail-closed -> Earn again.
3. Self-compute (10% fee) vs. Marketplace compute (25% fee) vs. Mixed jobs.
4. Withdrawable (earned) vs. Non-withdrawable (purchased) balance separation.
5. Strict double-entry ledger reconciliation with zero floating-point drift.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from services.billing.ledger import (
    AccountType,
    BillingError,
    InsufficientBalanceError,
    MICRO_UNIT_SCALE,
)
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_credits import (
    OWNER_EARNED,
    OWNER_PURCHASED,
    OwnerCreditLedger,
)
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.owner_job_accounting import (
    ProviderOwnerShare,
    quote_owner_job,
    settle_owner_job,
)


class UnifiedMultiRigAccountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.ledger_path = self.work_dir / "ledger.jsonl"
        self.owner_db_path = self.work_dir / "owners.db"
        self.ledger = GatewayOwnerCreditLedger(storage_path=self.ledger_path)
        self.owner_store = OwnerAccountStore(self.owner_db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_multi_rig_earnings_aggregation(self) -> None:
        """Multiple rigs owned by one account aggregate earnings into the owner's earned balance."""
        owner_id = "owner_alice"
        self.owner_store.ensure_owner(owner_id)
        self.owner_store.bind_provider_node(owner_id, "rig-01")
        self.owner_store.bind_provider_node(owner_id, "rig-02")
        self.owner_store.bind_provider_node(owner_id, "laptop-01")

        # Verify all 3 nodes resolve to Alice
        self.assertEqual(self.owner_store.owner_for_provider_node("rig-01"), owner_id)
        self.assertEqual(self.owner_store.owner_for_provider_node("rig-02"), owner_id)
        self.assertEqual(self.owner_store.owner_for_provider_node("laptop-01"), owner_id)
        self.assertEqual(set(self.owner_store.list_provider_nodes(owner_id)), {"rig-01", "rig-02", "laptop-01"})

        # Rigs perform compute for external customer
        customer_id = "owner_bob"
        self.ledger.deposit_owner_purchased_credits(
            owner_id=customer_id,
            amount_micro_units=10 * MICRO_UNIT_SCALE,  # $10.00
            payment_reference="pay_bob_01",
        )

        shares = [
            ProviderOwnerShare(provider_node_id="rig-01", owner_id=owner_id, ratio=0.5),
            ProviderOwnerShare(provider_node_id="rig-02", owner_id=owner_id, ratio=0.3),
            ProviderOwnerShare(provider_node_id="laptop-01", owner_id=owner_id, ratio=0.2),
        ]

        quote = quote_owner_job(
            customer_owner_id=customer_id,
            gross_reference_micro_units=2 * MICRO_UNIT_SCALE,  # $2.00
            provider_shares=shares,
            marketplace_fee_bps=2500,  # 25%
        )

        self.assertEqual(quote.customer_charge_micro_units, 2_000_000)
        self.assertEqual(quote.operator_fee_micro_units, 500_000)  # $0.50 platform fee
        # Total provider earned pool: $1.50 = 1,500,000 micro-units
        self.assertEqual(quote.provider_earned_by_owner, ((owner_id, 1_500_000),))

        settle_owner_job(
            ledger=self.ledger,
            job_id="job_multi_rig_01",
            quote=quote,
            description="Multi-rig compute execution",
        )

        alice_balances = self.ledger.get_owner_balances(owner_id)
        self.assertEqual(alice_balances.earned_micro_units, 1_500_000)
        self.assertEqual(alice_balances.withdrawable_micro_units, 1_500_000)
        self.assertEqual(alice_balances.total_spendable_micro_units, 1_500_000)

        bob_balances = self.ledger.get_owner_balances(customer_id)
        self.assertEqual(bob_balances.purchased_micro_units, 8_000_000)  # $8.00 remaining

        self.ledger.reconcile()

    def test_circular_credit_spend_to_zero_and_earn_again(self) -> None:
        """Earn on GPU -> Spend balance on API inference -> Reach 0 -> Fail closed -> Earn more."""
        owner_id = "owner_miner"
        self.owner_store.ensure_owner(owner_id)
        self.owner_store.bind_provider_node(owner_id, "miner-gpu-1")

        # 1. Earn $5.00 from provider compute
        external_customer = "owner_external"
        self.ledger.deposit_owner_purchased_credits(
            owner_id=external_customer,
            amount_micro_units=20 * MICRO_UNIT_SCALE,
            payment_reference="pay_ext_01",
        )

        quote1 = quote_owner_job(
            customer_owner_id=external_customer,
            gross_reference_micro_units=5 * MICRO_UNIT_SCALE,
            provider_shares=[ProviderOwnerShare("miner-gpu-1", owner_id, 1.0)],
            marketplace_fee_bps=2000,  # 20%
        )
        settle_owner_job(self.ledger, "job_earn_01", quote1)

        miner_bal = self.ledger.get_owner_balances(owner_id)
        self.assertEqual(miner_bal.earned_micro_units, 4_000_000)  # $4.00 net earned ($5 gross - 20% fee)
        self.assertEqual(miner_bal.total_spendable_micro_units, 4_000_000)

        # 2. Spend earned credits on API inference from foreign hardware (Bob)
        foreign_owner = "owner_bob"
        self.owner_store.ensure_owner(foreign_owner)
        self.owner_store.bind_provider_node(foreign_owner, "bob-node-1")

        # Spend $2.50
        quote2 = quote_owner_job(
            customer_owner_id=owner_id,
            gross_reference_micro_units=2_500_000,
            provider_shares=[ProviderOwnerShare("bob-node-1", foreign_owner, 1.0)],
            marketplace_fee_bps=2000,
        )
        settle_owner_job(self.ledger, "job_spend_01", quote2)

        miner_bal = self.ledger.get_owner_balances(owner_id)
        self.assertEqual(miner_bal.earned_micro_units, 1_500_000)  # $1.50 left

        # Spend remaining $1.50 down to exactly 0
        quote3 = quote_owner_job(
            customer_owner_id=owner_id,
            gross_reference_micro_units=1_500_000,
            provider_shares=[ProviderOwnerShare("bob-node-1", foreign_owner, 1.0)],
            marketplace_fee_bps=2000,
        )
        settle_owner_job(self.ledger, "job_spend_02", quote3)

        miner_bal = self.ledger.get_owner_balances(owner_id)
        self.assertEqual(miner_bal.earned_micro_units, 0)
        self.assertEqual(miner_bal.total_spendable_micro_units, 0)

        # 3. Subsequent API spend fails closed due to zero balance
        quote4 = quote_owner_job(
            customer_owner_id=owner_id,
            gross_reference_micro_units=100_000,
            provider_shares=[ProviderOwnerShare("bob-node-1", foreign_owner, 1.0)],
        )
        with self.assertRaises(InsufficientBalanceError):
            settle_owner_job(self.ledger, "job_spend_fail_zero", quote4)

        # 4. Provide more compute -> balance restored -> API works again
        quote5 = quote_owner_job(
            customer_owner_id=external_customer,
            gross_reference_micro_units=3 * MICRO_UNIT_SCALE,
            provider_shares=[ProviderOwnerShare("miner-gpu-1", owner_id, 1.0)],
            marketplace_fee_bps=2000,
        )
        settle_owner_job(self.ledger, "job_earn_02", quote5)

        miner_bal = self.ledger.get_owner_balances(owner_id)
        self.assertEqual(miner_bal.earned_micro_units, 2_400_000)  # $2.40 new earned balance

        # Now API call succeeds again
        settle_owner_job(self.ledger, "job_spend_03", quote4)
        miner_bal = self.ledger.get_owner_balances(owner_id)
        self.assertEqual(miner_bal.earned_micro_units, 2_300_000)

        self.ledger.reconcile()

    def test_self_compute_reduced_fee_vs_marketplace_fee(self) -> None:
        """Self-compute applies reduced infrastructure fee (10%) while marketplace applies 25%."""
        alice_id = "owner_alice"
        bob_id = "owner_bob"
        self.owner_store.ensure_owner(alice_id)
        self.owner_store.ensure_owner(bob_id)
        self.owner_store.bind_provider_node(alice_id, "alice-gpu-1")
        self.owner_store.bind_provider_node(bob_id, "bob-gpu-1")

        self.ledger.deposit_owner_purchased_credits(
            owner_id=alice_id,
            amount_micro_units=10 * MICRO_UNIT_SCALE,
            payment_reference="pay_alice_topup",
        )

        # Case A: 100% Self-Compute (Alice runs on Alice's GPU)
        # Gross job value $2.00, self compute fee 10% -> Alice is only charged $0.20 infrastructure fee!
        quote_self = quote_owner_job(
            customer_owner_id=alice_id,
            gross_reference_micro_units=2 * MICRO_UNIT_SCALE,
            provider_shares=[ProviderOwnerShare("alice-gpu-1", alice_id, 1.0)],
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,  # 10%
        )
        self.assertTrue(quote_self.is_pure_self_compute)
        self.assertEqual(quote_self.customer_charge_micro_units, 200_000)  # $0.20 fee only
        self.assertEqual(quote_self.operator_fee_micro_units, 200_000)
        self.assertEqual(quote_self.provider_earned_by_owner, ())

        settle_owner_job(self.ledger, "job_self_01", quote_self)
        alice_bal = self.ledger.get_owner_balances(alice_id)
        self.assertEqual(alice_bal.purchased_micro_units, 9_800_000)  # $9.80 left ($10 - $0.20)

        # Case B: Mixed Job (60% Alice GPU, 40% Bob GPU on $2.00 gross request)
        # Gross: $2.00 (Alice share $1.20, Bob share $0.80)
        # Alice self-fee: 10% of $1.20 = $0.12 (120,000 µ$)
        # Bob marketplace: $0.80 full debit, 25% operator fee = $0.20 (200,000 µ$), Bob gets $0.60 (600,000 µ$)
        # Total Alice debit: $0.12 + $0.80 = $0.92 (920,000 µ$)
        quote_mixed = quote_owner_job(
            customer_owner_id=alice_id,
            gross_reference_micro_units=2 * MICRO_UNIT_SCALE,
            provider_shares=[
                ProviderOwnerShare("alice-gpu-1", alice_id, 0.6),
                ProviderOwnerShare("bob-gpu-1", bob_id, 0.4),
            ],
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,
        )
        self.assertFalse(quote_mixed.is_pure_self_compute)
        self.assertFalse(quote_mixed.is_pure_marketplace)
        self.assertEqual(quote_mixed.customer_charge_micro_units, 920_000)
        self.assertEqual(quote_mixed.operator_fee_micro_units, 320_000)  # $0.12 + $0.20
        self.assertEqual(quote_mixed.provider_earned_by_owner, ((bob_id, 600_000),))

        settle_owner_job(self.ledger, "job_mixed_01", quote_mixed)
        alice_bal = self.ledger.get_owner_balances(alice_id)
        self.assertEqual(alice_bal.purchased_micro_units, 8_880_000)  # $9.80 - $0.92 = $8.88

        bob_bal = self.ledger.get_owner_balances(bob_id)
        self.assertEqual(bob_bal.earned_micro_units, 600_000)  # $0.60 earned

        self.ledger.reconcile()

    def test_withdrawable_earned_vs_purchased_invariants(self) -> None:
        """Purchased credits cannot be withdrawn; only earned credits can be reserved and paid out."""
        from services.billing.owner_settlement import PayoutCapableOwnerLedger

        payout_ledger = PayoutCapableOwnerLedger(storage_path=self.work_dir / "payout_ledger.jsonl")
        owner_id = "owner_mixed_bal"
        self.owner_store.ensure_owner(owner_id)

        # Deposit $20 purchased
        payout_ledger.deposit_owner_purchased_credits(
            owner_id=owner_id,
            amount_micro_units=20 * MICRO_UNIT_SCALE,
            payment_reference="pay_topup_20",
        )

        # Credit $10 earned
        payout_ledger.credit_owner_earned_credits(
            owner_id=owner_id,
            amount_micro_units=10 * MICRO_UNIT_SCALE,
            earning_reference="ref_gpu_earn_10",
        )

        bal = payout_ledger.get_owner_balances(owner_id)
        self.assertEqual(bal.purchased_micro_units, 20_000_000)
        self.assertEqual(bal.earned_micro_units, 10_000_000)
        self.assertEqual(bal.total_spendable_micro_units, 30_000_000)
        self.assertEqual(bal.withdrawable_micro_units, 10_000_000)

        # Reserve $6 from earned balance for withdrawal
        payout_ledger.reserve_owner_withdrawal(
            owner_id=owner_id,
            amount_micro_units=6 * MICRO_UNIT_SCALE,
            settlement_reference="payout_01",
        )

        bal = payout_ledger.get_owner_balances(owner_id)
        self.assertEqual(bal.earned_micro_units, 4_000_000)
        self.assertEqual(bal.purchased_micro_units, 20_000_000)
        self.assertEqual(bal.withdrawable_micro_units, 4_000_000)
        self.assertEqual(payout_ledger.owner_withdrawal_pending_micro_units(owner_id), 6_000_000)

        # Finalize withdrawal
        payout_ledger.finalize_owner_withdrawal(
            owner_id=owner_id,
            amount_micro_units=6 * MICRO_UNIT_SCALE,
            settlement_reference="payout_01",
        )
        self.assertEqual(payout_ledger.owner_withdrawal_pending_micro_units(owner_id), 0)

        # Attempting to reserve more than remaining earned ($4) fails even though purchased balance is $20
        with self.assertRaises(InsufficientBalanceError):
            payout_ledger.reserve_owner_withdrawal(
                owner_id=owner_id,
                amount_micro_units=5 * MICRO_UNIT_SCALE,
                settlement_reference="payout_fail_purchased_leak",
            )

        payout_ledger.reconcile()


if __name__ == "__main__":
    unittest.main()
