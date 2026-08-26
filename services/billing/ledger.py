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


from services.common.pricing import (
    DEFAULT_PRICE_TIERS,
    ModelPriceTier,
    calculate_token_charge_micro,
    get_price_tier,
)


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


import secrets
import threading
import time


@dataclass
class CreditHold:
    """Pre-inference financial hold reserved against customer deposit balance."""
    hold_id: str
    account_id: str
    amount_micro_units: int
    model_id: str
    created_at: str
    expires_at: float
    status: str = "active"  # "active", "captured", "released", "expired"

    @property
    def is_active(self) -> bool:
        return self.status == "active" and time.time() < self.expires_at


class Ledger:
    def __init__(
        self,
        storage_path: Path | None = None,
        network_fee_bps: int | None = None,
        operator_treasury_wallet: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
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
        self._holds: dict[str, CreditHold] = {}  # hold_id -> CreditHold
        if self.storage_path and self.storage_path.exists():
            with self._lock:
                self._load_from_disk()

    def get_available_balance(self, account_id: str) -> int:
        """Returns the customer spendable balance after deducting unexpired active credit holds."""
        with self._lock:
            raw_balance = self.get_balance(account_id)
            active_holds = sum(
                h.amount_micro_units
                for h in self._holds.values()
                if h.account_id == account_id and h.is_active
            )
            return max(0, raw_balance - active_holds)

    def create_hold(
        self,
        *,
        account_id: str,
        amount_micro_units: int,
        model_id: str = "",
        ttl_seconds: float = 600.0,
        hold_id: str | None = None,
    ) -> CreditHold:
        """Atomically reserves a credit hold if the customer's available balance is sufficient."""
        if amount_micro_units <= 0:
            raise BillingError("hold amount must be positive")
        with self._lock:
            avail = self.get_available_balance(account_id)
            if avail < amount_micro_units:
                raise InsufficientBalanceError(
                    f"customer {account_id} available balance ({avail}) insufficient for hold ({amount_micro_units})"
                )
            hid = hold_id or f"hold_{secrets.token_hex(12)}"
            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            hold = CreditHold(
                hold_id=hid,
                account_id=account_id,
                amount_micro_units=amount_micro_units,
                model_id=model_id,
                created_at=now_iso,
                expires_at=time.time() + max(5.0, ttl_seconds),
                status="active",
            )
            self._holds[hid] = hold
            return hold

    def renew_hold(self, hold_id: str, additional_seconds: float = 300.0) -> bool:
        """Renews an active credit hold lease."""
        with self._lock:
            hold = self._holds.get(hold_id)
            if hold and hold.status == "active":
                hold.expires_at = max(hold.expires_at, time.time()) + additional_seconds
                return True
            return False

    def release_hold(self, hold_id: str) -> bool:
        """Releases an active credit hold, immediately restoring available customer balance."""
        with self._lock:
            hold = self._holds.get(hold_id)
            if hold and hold.status == "active":
                hold.status = "released"
                return True
            return False

    def capture_hold(
        self,
        *,
        hold_id: str,
        job_id: str,
        customer_account_id: str,
        provider_shares: list[tuple[str, float]],
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        network_fee_bps: int | None = None,
    ) -> Transaction:
        """Captures actual inference compute cost against an active hold and releases any remainder."""
        with self._lock:
            hold = self._holds.get(hold_id)
            if not hold:
                raise BillingError(f"Credit hold '{hold_id}' not found")
            if hold.status != "active":
                raise BillingError(f"Credit hold '{hold_id}' is not active (status: {hold.status})")
            if hold.account_id != customer_account_id:
                raise BillingError(f"Credit hold '{hold_id}' account mismatch ({hold.account_id} != {customer_account_id})")
            if hold.model_id and hold.model_id != model_id:
                raise BillingError(f"Credit hold '{hold_id}' model mismatch ({hold.model_id} != {model_id})")
            if not hold.is_active:
                raise BillingError(f"Credit hold '{hold_id}' has expired")

            actual_charge = calculate_token_charge_micro(
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

            # Check if actual charge exceeds hold amount
            if actual_charge > hold.amount_micro_units:
                extra = actual_charge - hold.amount_micro_units
                avail = self.get_available_balance(customer_account_id)
                if avail < extra:
                    raise InsufficientBalanceError(
                        f"Actual compute charge ({actual_charge} µ$) exceeded hold ({hold.amount_micro_units} µ$) and available balance ({avail} µ$) cannot cover extra {extra} µ$"
                    )
                # Expand hold to cover extra
                hold.amount_micro_units = actual_charge

            try:
                tx = self.record_job_execution(
                    job_id=job_id,
                    customer_account_id=customer_account_id,
                    provider_shares=provider_shares,
                    model_id=model_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    network_fee_bps=network_fee_bps,
                )
                hold.status = "captured"
                return tx
            finally:
                if hold.status == "active":
                    hold.status = "released"

    def deposit_customer_credits(
        self,
        *,
        customer_account_id: str,
        amount_micro_units: int,
        payment_reference: str,
    ) -> Transaction:
        with self._lock:
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

    def has_received_initial_grant(self, customer_account_id: str) -> bool:
        """Checks if the customer account has already received an initial promotional grant."""
        with self._lock:
            target_prefix = f"deposit:initial_grant_{customer_account_id}"
            for event_id in self._processed_events:
                if event_id.startswith(target_prefix):
                    return True
            return False

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
        with self._lock:
            event_id = f"job:{job_id}"
            if event_id in self._processed_events:
                raise DuplicateEventError(f"job {job_id} already billed")

        total_charge_micro = calculate_token_charge_micro(
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            return self._balances.get(account_id, 0)

    def get_platform_revenue_micro_units(self) -> int:
        """Return the accumulated net platform revenue (default 25% platform margin) in micro-units."""
        with self._lock:
            return self.get_balance("revenue:network_fee")

    def get_platform_revenue_usd(self) -> float:
        """Return the accumulated net platform revenue in USD."""
        with self._lock:
            return round(self.get_platform_revenue_micro_units() / MICRO_UNIT_SCALE, 4)

    def reconcile(self) -> dict[str, Any]:
        """Perform comprehensive mathematical audit of the entire journal."""
        with self._lock:
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
        with self._lock:
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
