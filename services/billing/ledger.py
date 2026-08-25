#!/usr/bin/env python3
"""ComputeMesh Double-Entry Billing & Settlement Ledger.

Converts accepted job metering events into immutable, auditable double-entry
ledger entries with integer micro-unit precision, ensuring zero floating-point drift,
strict idempotency, and automated provider payout settlements.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MICRO_UNIT_SCALE = 1_000_000  # 1.000000 currency unit = 1,000,000 micro-units
DEFAULT_NETWORK_FEE_BPS = 2500  # 25.00% network operator fee (2500 Basis Points = 25%)
MINIMUM_PAYOUT_MICRO_UNITS = 25_000_000  # $25.00 minimum threshold for automated withdrawal


class BillingError(Exception):
    """Base exception for billing and ledger violations."""


class InsufficientBalanceError(BillingError):
    """Raised when a customer deposit balance cannot cover an inference charge."""


class DuplicateEventError(BillingError):
    """Raised when a metering event with an existing event_id is re-submitted."""


class LedgerReconciliationError(BillingError):
    """Raised when total debits do not equal total credits across the journal."""


class AccountType(enum.Enum):
    CUSTOMER_DEPOSIT = "liability:customer_deposit"
    PROVIDER_PAYABLE = "liability:provider_payable"
    NETWORK_FEE_REVENUE = "revenue:network_fee"
    PAYMENT_GATEWAY_ESCROW = "asset:payment_gateway_escrow"
    PAYOUT_SETTLEMENT = "expense:payout_settlement"


@dataclass(frozen=True)
class ModelPriceTier:
    model_id: str
    prompt_micro_per_token: int      # e.g., 200 micro-units = $0.20 per 1M tokens
    completion_micro_per_token: int  # e.g., 200 micro-units = $0.20 per 1M tokens


# Standard default pricing catalog in micro-units per token
DEFAULT_PRICE_TIERS: dict[str, ModelPriceTier] = {
    "qwen/qwen2.5-0.5b-instruct": ModelPriceTier("qwen/qwen2.5-0.5b-instruct", 50, 50),
    "qwen/qwen2.5-7b-instruct": ModelPriceTier("qwen/qwen2.5-7b-instruct", 200, 200),
    "qwen/qwen2.5-14b-instruct": ModelPriceTier("qwen/qwen2.5-14b-instruct", 350, 350),
    "qwen/qwen2.5-32b-instruct": ModelPriceTier("qwen/qwen2.5-32b-instruct", 700, 700),
    "llama/llama-3.1-70b-instruct": ModelPriceTier("llama/llama-3.1-70b-instruct", 1400, 1400),
}


@dataclass(frozen=True)
class Posting:
    account_id: str
    account_type: str
    debit_micro_units: int = 0
    credit_micro_units: int = 0

    def __post_init__(self) -> None:
        if self.debit_micro_units < 0 or self.credit_micro_units < 0:
            raise BillingError("posting amounts must be non-negative integers")
        if (self.debit_micro_units > 0) == (self.credit_micro_units > 0):
            raise BillingError("a posting must specify exactly one of debit or credit > 0")


@dataclass(frozen=True)
class Transaction:
    tx_id: str
    event_id: str
    created_at: str
    description: str
    postings: tuple[Posting, ...]

    def __post_init__(self) -> None:
        total_debits = sum(p.debit_micro_units for p in self.postings)
        total_credits = sum(p.credit_micro_units for p in self.postings)
        if total_debits != total_credits:
            raise BillingError(
                f"unbalanced transaction {self.tx_id}: debits={total_debits} != credits={total_credits}"
            )
        if total_debits <= 0:
            raise BillingError("transaction must have total transfer > 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "event_id": self.event_id,
            "created_at": self.created_at,
            "description": self.description,
            "total_micro_units": sum(p.debit_micro_units for p in self.postings),
            "postings": [asdict(p) for p in self.postings],
        }


@dataclass(frozen=True)
class PayoutSummary:
    payout_id: str
    provider_node_id: str
    amount_micro_units: int
    amount_usd: float
    wallet_address: str
    created_at: str


class Ledger:
    def __init__(
        self,
        storage_path: Path | None = None,
        network_fee_bps: int | None = None,
        operator_treasury_wallet: str | None = None,
    ) -> None:
        self.storage_path = Path(storage_path) if storage_path else None
        env_fee = os.environ.get("COMPUTEMESH_OPERATOR_FEE_BPS")
        self.network_fee_bps = (
            network_fee_bps
            if network_fee_bps is not None
            else (int(env_fee) if env_fee else DEFAULT_NETWORK_FEE_BPS)
        )
        self.operator_treasury_wallet = (
            operator_treasury_wallet
            or os.environ.get("COMPUTEMESH_OPERATOR_TREASURY_WALLET", "")
        )
        self._transactions: list[Transaction] = []
        self._processed_events: set[str] = set()
        self._balances: dict[str, int] = {}  # account_id -> signed net balance
        self._account_types: dict[str, str] = {}
        if self.storage_path and self.storage_path.exists():
            self._load_from_disk()

    def deposit_customer_credits(
        self,
        *,
        customer_account_id: str,
        amount_micro_units: int,
        payment_reference: str,
    ) -> Transaction:
        if amount_micro_units <= 0:
            raise BillingError("deposit amount must be positive")
        event_id = f"deposit:{payment_reference}"
        if event_id in self._processed_events:
            raise DuplicateEventError(f"payment reference {payment_reference} already deposited")

        tx_id = f"tx_dep_{hashlib.sha256(event_id.encode('utf-8')).hexdigest()[:16]}"
        tx = Transaction(
            tx_id=tx_id,
            event_id=event_id,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            description=f"Prepaid credit top-up via {payment_reference}",
            postings=(
                Posting(
                    account_id="gateway:escrow",
                    account_type=AccountType.PAYMENT_GATEWAY_ESCROW.value,
                    debit_micro_units=amount_micro_units,
                ),
                Posting(
                    account_id=customer_account_id,
                    account_type=AccountType.CUSTOMER_DEPOSIT.value,
                    credit_micro_units=amount_micro_units,
                ),
            ),
        )
        self._record_transaction(tx)
        return tx

    def record_job_execution(
        self,
        *,
        job_id: str,
        customer_account_id: str,
        provider_shares: list[tuple[str, float]],  # list of (provider_node_id, layer_ratio)
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        network_fee_bps: int | None = None,
    ) -> Transaction:
        event_id = f"job:{job_id}"
        if event_id in self._processed_events:
            raise DuplicateEventError(f"job {job_id} already billed")

        price_tier = DEFAULT_PRICE_TIERS.get(model_id, DEFAULT_PRICE_TIERS["qwen/qwen2.5-7b-instruct"])
        total_charge_micro = (
            prompt_tokens * price_tier.prompt_micro_per_token
            + completion_tokens * price_tier.completion_micro_per_token
        )
        if total_charge_micro <= 0:
            total_charge_micro = 1  # Minimum 1 micro-unit charge for metered request

        customer_balance = self.get_balance(customer_account_id)
        if customer_balance < total_charge_micro:
            raise InsufficientBalanceError(
                f"customer {customer_account_id} balance ({customer_balance}) insufficient for charge ({total_charge_micro})"
            )

        # Split: Operator Network Fee (e.g. 20% to 30%, default 25%, or 0% for provider self-compute), Remaining Provider Pool
        fee_bps = self.network_fee_bps if network_fee_bps is None else max(0, network_fee_bps)
        network_fee = (total_charge_micro * fee_bps) // 10000
        provider_pool = total_charge_micro - network_fee

        postings: list[Posting] = [
            Posting(
                account_id=customer_account_id,
                account_type=AccountType.CUSTOMER_DEPOSIT.value,
                debit_micro_units=total_charge_micro,
            ),
        ]
        if network_fee > 0:
            postings.append(
                Posting(
                    account_id="revenue:network_fee",
                    account_type=AccountType.NETWORK_FEE_REVENUE.value,
                    credit_micro_units=network_fee,
                )
            )

        # Allocate provider pool proportionally
        allocated_provider_units = 0
        total_shares = sum(ratio for _, ratio in provider_shares)
        for i, (provider_id, ratio) in enumerate(provider_shares):
            if i == len(provider_shares) - 1:
                # Assign remainder to avoid rounding leakage
                share_units = provider_pool - allocated_provider_units
            else:
                share_units = int((provider_pool * ratio) / total_shares)
                allocated_provider_units += share_units

            if share_units > 0:
                postings.append(
                    Posting(
                        account_id=f"provider:{provider_id}",
                        account_type=AccountType.PROVIDER_PAYABLE.value,
                        credit_micro_units=share_units,
                    )
                )

        tx_id = f"tx_job_{hashlib.sha256(event_id.encode('utf-8')).hexdigest()[:16]}"
        tx = Transaction(
            tx_id=tx_id,
            event_id=event_id,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            description=f"Inference execution for {job_id} ({model_id}, {prompt_tokens}+{completion_tokens} tokens)",
            postings=tuple(postings),
        )
        self._record_transaction(tx)
        return tx

    def create_operator_treasury_payout(
        self,
        wallet_address: str | None = None,
        settlement_reference: str | None = None,
    ) -> tuple[Transaction, PayoutSummary]:
        """Transfers accumulated platform operator network fee revenue directly to the operator's treasury wallet."""
        wallet = wallet_address or self.operator_treasury_wallet
        if not wallet:
            raise BillingError("No operator treasury wallet address specified for payout.")

        balance = self.get_balance("revenue:network_fee")
        if balance <= 0:
            raise BillingError("Operator network fee treasury balance is zero.")

        event_id = f"payout:operator_treasury:{settlement_reference or secrets_token_hex(6)}"
        if event_id in self._processed_events:
            raise DuplicateEventError(f"operator settlement {settlement_reference} already paid out")
        tx_id = f"tx_op_pay_{hashlib.sha256(event_id.encode('utf-8')).hexdigest()[:16]}"

        tx = Transaction(
            tx_id=tx_id,
            event_id=event_id,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            description=f"Operator network protocol fee revenue payout to treasury {wallet}",
            postings=(
                Posting(
                    account_id="revenue:network_fee",
                    account_type=AccountType.NETWORK_FEE_REVENUE.value,
                    debit_micro_units=balance,
                ),
                Posting(
                    account_id="expense:settlements",
                    account_type=AccountType.PAYOUT_SETTLEMENT.value,
                    credit_micro_units=balance,
                ),
            ),
        )
        self._record_transaction(tx)

        summary = PayoutSummary(
            payout_id=tx_id,
            provider_node_id="operator_treasury",
            amount_micro_units=balance,
            amount_usd=round(balance / MICRO_UNIT_SCALE, 4),
            wallet_address=wallet,
            created_at=tx.created_at,
        )
        return tx, summary

    def create_provider_payout(
        self,
        *,
        provider_node_id: str,
        wallet_address: str,
        settlement_reference: str | None = None,
    ) -> tuple[Transaction, PayoutSummary]:
        provider_account_id = f"provider:{provider_node_id}"
        balance = self.get_balance(provider_account_id)
        if balance < MINIMUM_PAYOUT_MICRO_UNITS:
            raise BillingError(
                f"provider balance {balance} below minimum payout threshold {MINIMUM_PAYOUT_MICRO_UNITS}"
            )

        event_id = f"payout:{provider_node_id}:{settlement_reference or secrets_token_hex(6)}"
        if event_id in self._processed_events:
            raise DuplicateEventError(f"provider settlement {settlement_reference} already paid out")
        tx_id = f"tx_pay_{hashlib.sha256(event_id.encode('utf-8')).hexdigest()[:16]}"

        tx = Transaction(
            tx_id=tx_id,
            event_id=event_id,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            description=f"Automated settlement withdrawal to {wallet_address}",
            postings=(
                Posting(
                    account_id=provider_account_id,
                    account_type=AccountType.PROVIDER_PAYABLE.value,
                    debit_micro_units=balance,
                ),
                Posting(
                    account_id="expense:settlements",
                    account_type=AccountType.PAYOUT_SETTLEMENT.value,
                    credit_micro_units=balance,
                ),
            ),
        )
        self._record_transaction(tx)

        summary = PayoutSummary(
            payout_id=tx_id,
            provider_node_id=provider_node_id,
            amount_micro_units=balance,
            amount_usd=round(balance / MICRO_UNIT_SCALE, 4),
            wallet_address=wallet_address,
            created_at=tx.created_at,
        )
        return tx, summary

    def get_balance(self, account_id: str) -> int:
        return self._balances.get(account_id, 0)

    def get_platform_revenue_micro_units(self) -> int:
        """Return the accumulated net platform revenue (default 25% platform margin) in micro-units."""
        return self.get_balance("revenue:network_fee")

    def get_platform_revenue_usd(self) -> float:
        """Return the accumulated net platform revenue in USD."""
        return round(self.get_platform_revenue_micro_units() / MICRO_UNIT_SCALE, 4)

    def reconcile(self) -> dict[str, Any]:
        """Perform comprehensive mathematical audit of the entire journal."""
        sum_debits = 0
        sum_credits = 0
        computed_balances: dict[str, int] = {}

        for tx in self._transactions:
            for p in tx.postings:
                sum_debits += p.debit_micro_units
                sum_credits += p.credit_micro_units
                # In double-entry: Credits increase liabilities/revenues, debits increase assets/expenses
                if "liability" in p.account_type or "revenue" in p.account_type:
                    computed_balances[p.account_id] = (
                        computed_balances.get(p.account_id, 0) + p.credit_micro_units - p.debit_micro_units
                    )
                else:
                    computed_balances[p.account_id] = (
                        computed_balances.get(p.account_id, 0) + p.debit_micro_units - p.credit_micro_units
                    )

        if sum_debits != sum_credits:
            raise LedgerReconciliationError(f"global journal imbalance: debits={sum_debits} != credits={sum_credits}")

        for acc, bal in self._balances.items():
            if computed_balances.get(acc, 0) != bal:
                raise LedgerReconciliationError(
                    f"account {acc} balance drift: stored={bal} != computed={computed_balances.get(acc, 0)}"
                )

        return {
            "status": "balanced",
            "total_transactions": len(self._transactions),
            "total_turnover_micro_units": sum_debits,
            "total_turnover_usd": round(sum_debits / MICRO_UNIT_SCALE, 2),
            "active_accounts": len(self._balances),
            "audited_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def _record_transaction(self, tx: Transaction) -> None:
        for p in tx.postings:
            self._account_types[p.account_id] = p.account_type
            if "liability" in p.account_type or "revenue" in p.account_type:
                self._balances[p.account_id] = (
                    self._balances.get(p.account_id, 0) + p.credit_micro_units - p.debit_micro_units
                )
            else:
                self._balances[p.account_id] = (
                    self._balances.get(p.account_id, 0) + p.debit_micro_units - p.credit_micro_units
                )

        self._transactions.append(tx)
        self._processed_events.add(tx.event_id)
        if self.storage_path:
            self._append_to_disk(tx)

    def _append_to_disk(self, tx: Transaction) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(tx.to_dict()) + "\n")

    def _load_from_disk(self) -> None:
        with open(self.storage_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                postings = tuple(
                    Posting(
                        account_id=p["account_id"],
                        account_type=p["account_type"],
                        debit_micro_units=p.get("debit_micro_units", 0),
                        credit_micro_units=p.get("credit_micro_units", 0),
                    )
                    for p in data["postings"]
                )
                tx = Transaction(
                    tx_id=data["tx_id"],
                    event_id=data["event_id"],
                    created_at=data["created_at"],
                    description=data["description"],
                    postings=postings,
                )
                for p in tx.postings:
                    self._account_types[p.account_id] = p.account_type
                    if "liability" in p.account_type or "revenue" in p.account_type:
                        self._balances[p.account_id] = (
                            self._balances.get(p.account_id, 0) + p.credit_micro_units - p.debit_micro_units
                        )
                    else:
                        self._balances[p.account_id] = (
                            self._balances.get(p.account_id, 0) + p.debit_micro_units - p.credit_micro_units
                        )
                self._transactions.append(tx)
                self._processed_events.add(tx.event_id)


def secrets_token_hex(nbytes: int) -> str:
    import secrets
    return secrets.token_hex(nbytes)
