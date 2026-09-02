"""Unified owner-level credit buckets for ComputeMesh.

This is the migration-safe accounting foundation for the planned owner account model.
It does not replace the legacy customer/provider paths yet. Instead it adds explicit
owner buckets that can coexist in the same append-only double-entry journal:

- earned: provider earnings, spendable and withdrawable;
- purchased: paid top-ups, spendable but not withdrawable;
- promo: operator-funded onboarding credit, spendable but not withdrawable.

The class intentionally keeps funding-source provenance in the postings so future
promo restrictions, chargeback handling and payout rules can be enforced without
turning all balances into one indistinguishable number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import secrets
import time
from typing import Iterable

from services.billing.ledger import (
    BillingError,
    DuplicateEventError,
    InsufficientBalanceError,
    Posting,
    Transaction,
)
from services.billing.threadsafe_ledger import ThreadSafeLedger


OWNER_EARNED = "liability:owner_earned_credit"
OWNER_PURCHASED = "liability:owner_purchased_credit"
OWNER_PROMO = "liability:owner_promo_credit"
PROMO_GRANT_EXPENSE = "expense:promo_grants"
PROVIDER_EARNINGS_EXPENSE = "expense:provider_earnings"
PAYMENT_GATEWAY_ESCROW = "asset:payment_gateway_escrow"

SPEND_ORDER = ("earned", "purchased", "promo")
_BUCKET_TYPES = {
    "earned": OWNER_EARNED,
    "purchased": OWNER_PURCHASED,
    "promo": OWNER_PROMO,
}


@dataclass(frozen=True)
class CreditDestination:
    account_id: str
    account_type: str
    amount_micro_units: int


@dataclass(frozen=True)
class OwnerBalanceSnapshot:
    owner_id: str
    earned_micro_units: int
    purchased_micro_units: int
    promo_micro_units: int
    total_spendable_micro_units: int
    withdrawable_micro_units: int
    available_spendable_micro_units: int


@dataclass
class OwnerCreditHold:
    hold_id: str
    owner_id: str
    amount_micro_units: int
    allocations: tuple[tuple[str, int], ...]
    purpose: str
    created_at: str
    expires_at: float
    status: str = "active"

    @property
    def is_active(self) -> bool:
        return self.status == "active" and time.time() < self.expires_at


@dataclass(frozen=True)
class OwnerSpendResult:
    transaction: Transaction
    spent_earned_micro_units: int
    spent_purchased_micro_units: int
    spent_promo_micro_units: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_owner(owner_id: str) -> str:
    result = str(owner_id or "").strip()
    if not result:
        raise BillingError("owner_id is required")
    if len(result) > 256:
        raise BillingError("owner_id is too long")
    return result


def owner_bucket_account(owner_id: str, bucket: str) -> str:
    owner = _clean_owner(owner_id)
    if bucket not in _BUCKET_TYPES:
        raise BillingError(f"unknown owner credit bucket {bucket!r}")
    return f"owner:{owner}:{bucket}"


def _tx_id(prefix: str, event_id: str) -> str:
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]
    return f"tx_{prefix}_{digest}"


class OwnerCreditLedger(ThreadSafeLedger):
    """Thread-safe ledger with explicit owner credit provenance and reservations."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._owner_holds: dict[str, OwnerCreditHold] = {}

    def _ensure_new_event(self, event_id: str) -> None:
        if event_id in self._processed_events:
            raise DuplicateEventError(f"event {event_id!r} already recorded")

    def _bucket_balance(self, owner_id: str, bucket: str) -> int:
        return self.get_balance(owner_bucket_account(owner_id, bucket))

    def _reserved_by_bucket(self, owner_id: str, *, exclude_hold_id: str | None = None) -> dict[str, int]:
        reserved = {bucket: 0 for bucket in SPEND_ORDER}
        now = time.time()
        for hold in self._owner_holds.values():
            if hold.hold_id == exclude_hold_id or hold.owner_id != owner_id or hold.status != "active":
                continue
            if hold.expires_at <= now:
                hold.status = "expired"
                continue
            for bucket, amount in hold.allocations:
                reserved[bucket] += amount
        return reserved

    def get_owner_balances(self, owner_id: str) -> OwnerBalanceSnapshot:
        owner = _clean_owner(owner_id)
        with self._lock:
            earned = self._bucket_balance(owner, "earned")
            purchased = self._bucket_balance(owner, "purchased")
            promo = self._bucket_balance(owner, "promo")
            reserved = self._reserved_by_bucket(owner)
            available_earned = max(0, earned - reserved["earned"])
            available_purchased = max(0, purchased - reserved["purchased"])
            available_promo = max(0, promo - reserved["promo"])
            return OwnerBalanceSnapshot(
                owner_id=owner,
                earned_micro_units=earned,
                purchased_micro_units=purchased,
                promo_micro_units=promo,
                total_spendable_micro_units=max(0, earned) + max(0, purchased) + max(0, promo),
                withdrawable_micro_units=available_earned,
                available_spendable_micro_units=available_earned + available_purchased + available_promo,
            )

    def deposit_owner_purchased_credits(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        payment_reference: str,
    ) -> Transaction:
        owner = _clean_owner(owner_id)
        if amount_micro_units <= 0:
            raise BillingError("purchased credit amount must be positive")
        ref = str(payment_reference or "").strip()
        if not ref:
            raise BillingError("payment_reference is required")
        event_id = f"owner-purchase:{ref}"
        with self._lock:
            self._ensure_new_event(event_id)
            tx = Transaction(
                tx_id=_tx_id("owner_purchase", event_id),
                event_id=event_id,
                created_at=_utc_now(),
                description=f"Purchased ComputeMesh credits for owner {owner}",
                postings=(
                    Posting(
                        account_id="gateway:escrow",
                        account_type=PAYMENT_GATEWAY_ESCROW,
                        debit_micro_units=amount_micro_units,
                    ),
                    Posting(
                        account_id=owner_bucket_account(owner, "purchased"),
                        account_type=OWNER_PURCHASED,
                        credit_micro_units=amount_micro_units,
                    ),
                ),
            )
            self._record_transaction(tx)
            return tx

    def grant_owner_promo_credits(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        grant_reference: str,
        policy_version: str,
    ) -> Transaction:
        owner = _clean_owner(owner_id)
        if amount_micro_units <= 0:
            raise BillingError("promo credit amount must be positive")
        ref = str(grant_reference or "").strip()
        policy = str(policy_version or "").strip()
        if not ref or not policy:
            raise BillingError("grant_reference and policy_version are required")
        event_id = f"owner-promo:{ref}"
        with self._lock:
            self._ensure_new_event(event_id)
            tx = Transaction(
                tx_id=_tx_id("owner_promo", event_id),
                event_id=event_id,
                created_at=_utc_now(),
                description=f"Promo grant {policy} for owner {owner}",
                postings=(
                    Posting(
                        account_id="expense:promo_grants",
                        account_type=PROMO_GRANT_EXPENSE,
                        debit_micro_units=amount_micro_units,
                    ),
                    Posting(
                        account_id=owner_bucket_account(owner, "promo"),
                        account_type=OWNER_PROMO,
                        credit_micro_units=amount_micro_units,
                    ),
                ),
            )
            self._record_transaction(tx)
            return tx

    def credit_owner_earned_credits(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        earning_reference: str,
        description: str = "Verified provider earnings",
    ) -> Transaction:
        """Credit earned balance for migration/verified external earning events.

        Normal inference integration should eventually create customer debit,
        operator revenue and owner-earned provider credits in one atomic job
        transaction. This method exists for migration and already-verified earning
        events that arrive through a separate accounting boundary.
        """
        owner = _clean_owner(owner_id)
        if amount_micro_units <= 0:
            raise BillingError("earned credit amount must be positive")
        ref = str(earning_reference or "").strip()
        if not ref:
            raise BillingError("earning_reference is required")
        event_id = f"owner-earning:{ref}"
        with self._lock:
            self._ensure_new_event(event_id)
            tx = Transaction(
                tx_id=_tx_id("owner_earning", event_id),
                event_id=event_id,
                created_at=_utc_now(),
                description=f"{description} for owner {owner}",
                postings=(
                    Posting(
                        account_id="expense:provider_earnings",
                        account_type=PROVIDER_EARNINGS_EXPENSE,
                        debit_micro_units=amount_micro_units,
                    ),
                    Posting(
                        account_id=owner_bucket_account(owner, "earned"),
                        account_type=OWNER_EARNED,
                        credit_micro_units=amount_micro_units,
                    ),
                ),
            )
            self._record_transaction(tx)
            return tx

    def _allocate_spend(
        self,
        owner_id: str,
        amount_micro_units: int,
        *,
        exclude_hold_id: str | None = None,
    ) -> tuple[tuple[str, int], ...]:
        if amount_micro_units <= 0:
            raise BillingError("spend amount must be positive")
        reserved = self._reserved_by_bucket(owner_id, exclude_hold_id=exclude_hold_id)
        remaining = amount_micro_units
        allocations: list[tuple[str, int]] = []
        for bucket in SPEND_ORDER:
            available = max(0, self._bucket_balance(owner_id, bucket) - reserved[bucket])
            take = min(remaining, available)
            if take:
                allocations.append((bucket, take))
                remaining -= take
            if remaining == 0:
                break
        if remaining:
            available_total = amount_micro_units - remaining
            raise InsufficientBalanceError(
                f"owner {owner_id} available balance ({available_total}) insufficient for spend ({amount_micro_units})"
            )
        return tuple(allocations)

    @staticmethod
    def _validate_destinations(
        destinations: Iterable[CreditDestination],
        amount_micro_units: int,
    ) -> tuple[CreditDestination, ...]:
        items = tuple(destinations)
        if not items:
            raise BillingError("at least one credit destination is required")
        total = 0
        for item in items:
            if not item.account_id or not item.account_type or item.amount_micro_units <= 0:
                raise BillingError("invalid credit destination")
            total += item.amount_micro_units
        if total != amount_micro_units:
            raise BillingError(
                f"destination credits ({total}) do not equal spend amount ({amount_micro_units})"
            )
        return items

    def _record_owner_spend(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        allocations: tuple[tuple[str, int], ...],
        destinations: tuple[CreditDestination, ...],
        event_id: str,
        description: str,
    ) -> OwnerSpendResult:
        self._ensure_new_event(event_id)
        postings: list[Posting] = []
        spent = {bucket: 0 for bucket in SPEND_ORDER}
        for bucket, amount in allocations:
            spent[bucket] += amount
            postings.append(
                Posting(
                    account_id=owner_bucket_account(owner_id, bucket),
                    account_type=_BUCKET_TYPES[bucket],
                    debit_micro_units=amount,
                )
            )
        for destination in destinations:
            postings.append(
                Posting(
                    account_id=destination.account_id,
                    account_type=destination.account_type,
                    credit_micro_units=destination.amount_micro_units,
                )
            )
        tx = Transaction(
            tx_id=_tx_id("owner_spend", event_id),
            event_id=event_id,
            created_at=_utc_now(),
            description=description,
            postings=tuple(postings),
        )
        self._record_transaction(tx)
        return OwnerSpendResult(
            transaction=tx,
            spent_earned_micro_units=spent["earned"],
            spent_purchased_micro_units=spent["purchased"],
            spent_promo_micro_units=spent["promo"],
        )

    def spend_owner_credits(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        destinations: Iterable[CreditDestination],
        spend_reference: str,
        description: str = "ComputeMesh owner credit spend",
    ) -> OwnerSpendResult:
        owner = _clean_owner(owner_id)
        ref = str(spend_reference or "").strip()
        if not ref:
            raise BillingError("spend_reference is required")
        destination_items = self._validate_destinations(destinations, amount_micro_units)
        with self._lock:
            allocations = self._allocate_spend(owner, amount_micro_units)
            return self._record_owner_spend(
                owner_id=owner,
                amount_micro_units=amount_micro_units,
                allocations=allocations,
                destinations=destination_items,
                event_id=f"owner-spend:{ref}",
                description=description,
            )

    def create_owner_hold(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        purpose: str = "inference",
        ttl_seconds: float = 600.0,
        hold_id: str | None = None,
    ) -> OwnerCreditHold:
        owner = _clean_owner(owner_id)
        with self._lock:
            allocations = self._allocate_spend(owner, amount_micro_units)
            hid = hold_id or f"owner_hold_{secrets.token_hex(12)}"
            if hid in self._owner_holds:
                raise BillingError(f"owner hold {hid!r} already exists")
            hold = OwnerCreditHold(
                hold_id=hid,
                owner_id=owner,
                amount_micro_units=amount_micro_units,
                allocations=allocations,
                purpose=str(purpose or "inference"),
                created_at=_utc_now(),
                expires_at=time.time() + max(5.0, float(ttl_seconds)),
            )
            self._owner_holds[hid] = hold
            return hold

    def release_owner_hold(self, hold_id: str) -> bool:
        with self._lock:
            hold = self._owner_holds.get(str(hold_id))
            if hold is None or hold.status != "active":
                return False
            hold.status = "released"
            return True

    def capture_owner_hold(
        self,
        *,
        hold_id: str,
        actual_amount_micro_units: int,
        destinations: Iterable[CreditDestination],
        spend_reference: str,
        description: str = "ComputeMesh owner held credit spend",
    ) -> OwnerSpendResult:
        ref = str(spend_reference or "").strip()
        if not ref:
            raise BillingError("spend_reference is required")
        if actual_amount_micro_units <= 0:
            raise BillingError("actual spend must be positive")
        destination_items = self._validate_destinations(destinations, actual_amount_micro_units)
        with self._lock:
            hold = self._owner_holds.get(str(hold_id))
            if hold is None:
                raise BillingError(f"owner hold {hold_id!r} not found")
            if hold.status != "active":
                raise BillingError(f"owner hold {hold_id!r} is not active")
            if not hold.is_active:
                hold.status = "expired"
                raise BillingError(f"owner hold {hold_id!r} has expired")

            if actual_amount_micro_units <= hold.amount_micro_units:
                remaining = actual_amount_micro_units
                allocations: list[tuple[str, int]] = []
                for bucket, reserved_amount in hold.allocations:
                    take = min(remaining, reserved_amount)
                    if take:
                        allocations.append((bucket, take))
                        remaining -= take
                    if remaining == 0:
                        break
                selected = tuple(allocations)
            else:
                selected = self._allocate_spend(
                    hold.owner_id,
                    actual_amount_micro_units,
                    exclude_hold_id=hold.hold_id,
                )

            result = self._record_owner_spend(
                owner_id=hold.owner_id,
                amount_micro_units=actual_amount_micro_units,
                allocations=selected,
                destinations=destination_items,
                event_id=f"owner-spend:{ref}",
                description=description,
            )
            hold.status = "captured"
            return result

    def owner_withdrawable_micro_units(self, owner_id: str) -> int:
        """Only unreserved earned credits are withdrawable."""
        return self.get_owner_balances(owner_id).withdrawable_micro_units
