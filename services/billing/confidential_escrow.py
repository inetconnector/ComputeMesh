"""Durable double-entry credit escrow for confidential ComputeMesh jobs.

Unlike the legacy in-memory hold dictionaries, a confidential reservation is an
append-only journal event.  Owner credit provenance is preserved by moving each
reserved source bucket into a job-specific liability sub-account.  Settlement
consumes the actual amount and refunds the remainder in one balanced transaction;
release returns the whole reservation.

No prompt, output, ciphertext, token IDs, or activations are needed by this layer.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

from services.billing.ledger import BillingError, DuplicateEventError, Posting, Transaction
from services.billing.owner_credits import (
    OWNER_EARNED,
    OWNER_PROMO,
    OWNER_PURCHASED,
    SPEND_ORDER,
    CreditDestination,
    OwnerSpendResult,
    _BUCKET_TYPES,
    _clean_owner,
    _tx_id,
    _utc_now,
    owner_bucket_account,
)
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger


OWNER_CONFIDENTIAL_RESERVATION = "liability:owner_confidential_reservation"


@dataclass(frozen=True)
class ConfidentialCreditReservation:
    reservation_id: str
    owner_id: str
    amount_micro_units: int
    allocations: tuple[tuple[str, int], ...]
    reserve_transaction: Transaction
    state: str


@dataclass(frozen=True)
class ConfidentialCreditSettlement:
    reservation: ConfidentialCreditReservation
    transaction: Transaction
    charged_micro_units: int
    refunded_micro_units: int
    spent_earned_micro_units: int
    spent_purchased_micro_units: int
    spent_promo_micro_units: int


def _clean_reservation_id(reservation_id: str) -> str:
    value = str(reservation_id or "").strip()
    if not value or len(value) > 256:
        raise BillingError("reservation_id is required and must be <= 256 characters")
    return value


def _reservation_suffix(reservation_id: str) -> str:
    return hashlib.sha256(reservation_id.encode("utf-8")).hexdigest()[:24]


def confidential_reservation_account(owner_id: str, reservation_id: str, bucket: str) -> str:
    owner = _clean_owner(owner_id)
    ref = _clean_reservation_id(reservation_id)
    if bucket not in _BUCKET_TYPES:
        raise BillingError(f"unknown owner credit bucket {bucket!r}")
    return f"owner:{owner}:confidential_reservation:{_reservation_suffix(ref)}:{bucket}"


class ConfidentialEscrowOwnerCreditLedger(GatewayOwnerCreditLedger):
    """Owner ledger with restart-safe protected-job financial reservations."""

    def _transaction_for_event(self, event_id: str) -> Transaction | None:
        for tx in reversed(self._transactions):
            if tx.event_id == event_id:
                return tx
        return None

    def _reservation_from_transaction(
        self,
        *,
        owner_id: str,
        reservation_id: str,
        tx: Transaction,
    ) -> ConfidentialCreditReservation:
        owner = _clean_owner(owner_id)
        ref = _clean_reservation_id(reservation_id)
        allocations: list[tuple[str, int]] = []
        total = 0
        for bucket in SPEND_ORDER:
            source_account = owner_bucket_account(owner, bucket)
            reserved_account = confidential_reservation_account(owner, ref, bucket)
            debit = sum(
                posting.debit_micro_units
                for posting in tx.postings
                if posting.account_id == source_account
            )
            credit = sum(
                posting.credit_micro_units
                for posting in tx.postings
                if posting.account_id == reserved_account
            )
            if debit != credit:
                raise BillingError("confidential reservation journal provenance is inconsistent")
            if debit:
                allocations.append((bucket, debit))
                total += debit
        if total <= 0:
            raise BillingError("confidential reservation journal contains no owner credit allocation")
        state = "reserved"
        if self._transaction_for_event(f"confidential-settle:{ref}") is not None:
            state = "settled"
        elif self._transaction_for_event(f"confidential-release:{ref}") is not None:
            state = "released"
        return ConfidentialCreditReservation(
            reservation_id=ref,
            owner_id=owner,
            amount_micro_units=total,
            allocations=tuple(allocations),
            reserve_transaction=tx,
            state=state,
        )

    def get_confidential_reservation(
        self,
        *,
        owner_id: str,
        reservation_id: str,
    ) -> ConfidentialCreditReservation | None:
        owner = _clean_owner(owner_id)
        ref = _clean_reservation_id(reservation_id)
        with self._lock:
            tx = self._transaction_for_event(f"confidential-reserve:{ref}")
            if tx is None:
                return None
            return self._reservation_from_transaction(
                owner_id=owner,
                reservation_id=ref,
                tx=tx,
            )

    def reserve_confidential_credits(
        self,
        *,
        owner_id: str,
        reservation_id: str,
        amount_micro_units: int,
    ) -> ConfidentialCreditReservation:
        owner = _clean_owner(owner_id)
        ref = _clean_reservation_id(reservation_id)
        if amount_micro_units <= 0:
            raise BillingError("confidential reservation amount must be positive")
        event_id = f"confidential-reserve:{ref}"
        with self._lock:
            existing = self._transaction_for_event(event_id)
            if existing is not None:
                reservation = self._reservation_from_transaction(
                    owner_id=owner,
                    reservation_id=ref,
                    tx=existing,
                )
                if reservation.amount_micro_units != amount_micro_units:
                    raise BillingError("confidential reservation retry amount mismatch")
                return reservation

            allocations = self._allocate_spend(owner, amount_micro_units)
            postings: list[Posting] = []
            for bucket, amount in allocations:
                postings.extend(
                    (
                        Posting(
                            account_id=owner_bucket_account(owner, bucket),
                            account_type=_BUCKET_TYPES[bucket],
                            debit_micro_units=amount,
                        ),
                        Posting(
                            account_id=confidential_reservation_account(owner, ref, bucket),
                            account_type=OWNER_CONFIDENTIAL_RESERVATION,
                            credit_micro_units=amount,
                        ),
                    )
                )
            tx = Transaction(
                tx_id=_tx_id("conf_reserve", event_id),
                event_id=event_id,
                created_at=_utc_now(),
                description=f"Reserve owner credits for confidential job {ref}",
                postings=tuple(postings),
            )
            self._record_transaction(tx)
            return self._reservation_from_transaction(
                owner_id=owner,
                reservation_id=ref,
                tx=tx,
            )

    def release_confidential_reservation(
        self,
        *,
        owner_id: str,
        reservation_id: str,
    ) -> Transaction:
        owner = _clean_owner(owner_id)
        ref = _clean_reservation_id(reservation_id)
        event_id = f"confidential-release:{ref}"
        with self._lock:
            existing = self._transaction_for_event(event_id)
            if existing is not None:
                return existing
            if self._transaction_for_event(f"confidential-settle:{ref}") is not None:
                raise BillingError("settled confidential reservation cannot be released")
            reservation = self.get_confidential_reservation(owner_id=owner, reservation_id=ref)
            if reservation is None:
                raise BillingError("confidential reservation not found")
            postings: list[Posting] = []
            for bucket, amount in reservation.allocations:
                reserved_account = confidential_reservation_account(owner, ref, bucket)
                balance = self.get_balance(reserved_account)
                if balance != amount:
                    raise BillingError("confidential reservation balance is inconsistent")
                postings.extend(
                    (
                        Posting(
                            account_id=reserved_account,
                            account_type=OWNER_CONFIDENTIAL_RESERVATION,
                            debit_micro_units=amount,
                        ),
                        Posting(
                            account_id=owner_bucket_account(owner, bucket),
                            account_type=_BUCKET_TYPES[bucket],
                            credit_micro_units=amount,
                        ),
                    )
                )
            tx = Transaction(
                tx_id=_tx_id("conf_release", event_id),
                event_id=event_id,
                created_at=_utc_now(),
                description=f"Release confidential job reservation {ref}",
                postings=tuple(postings),
            )
            self._record_transaction(tx)
            return tx

    def settle_confidential_reservation(
        self,
        *,
        owner_id: str,
        reservation_id: str,
        actual_amount_micro_units: int,
        destinations: Iterable[CreditDestination],
    ) -> ConfidentialCreditSettlement:
        owner = _clean_owner(owner_id)
        ref = _clean_reservation_id(reservation_id)
        if actual_amount_micro_units <= 0:
            raise BillingError("confidential settlement amount must be positive")
        event_id = f"confidential-settle:{ref}"
        destination_items = self._validate_destinations(destinations, actual_amount_micro_units)
        with self._lock:
            existing = self._transaction_for_event(event_id)
            reservation = self.get_confidential_reservation(owner_id=owner, reservation_id=ref)
            if reservation is None:
                raise BillingError("confidential reservation not found")
            if existing is not None:
                return self._settlement_result_from_transaction(
                    reservation=reservation,
                    tx=existing,
                    actual_amount_micro_units=actual_amount_micro_units,
                    destinations=destination_items,
                )
            if self._transaction_for_event(f"confidential-release:{ref}") is not None:
                raise BillingError("released confidential reservation cannot be settled")
            if actual_amount_micro_units > reservation.amount_micro_units:
                raise BillingError("confidential usage exceeds pre-authorized reservation")

            remaining_charge = actual_amount_micro_units
            spent = {bucket: 0 for bucket in SPEND_ORDER}
            postings: list[Posting] = []
            for bucket, reserved_amount in reservation.allocations:
                reserved_account = confidential_reservation_account(owner, ref, bucket)
                balance = self.get_balance(reserved_account)
                if balance != reserved_amount:
                    raise BillingError("confidential reservation balance is inconsistent")
                charge = min(remaining_charge, reserved_amount)
                refund = reserved_amount - charge
                postings.append(
                    Posting(
                        account_id=reserved_account,
                        account_type=OWNER_CONFIDENTIAL_RESERVATION,
                        debit_micro_units=reserved_amount,
                    )
                )
                if refund:
                    postings.append(
                        Posting(
                            account_id=owner_bucket_account(owner, bucket),
                            account_type=_BUCKET_TYPES[bucket],
                            credit_micro_units=refund,
                        )
                    )
                if charge:
                    spent[bucket] += charge
                    remaining_charge -= charge
            if remaining_charge:
                raise BillingError("confidential reservation could not cover actual charge")
            for destination in destination_items:
                postings.append(
                    Posting(
                        account_id=destination.account_id,
                        account_type=destination.account_type,
                        credit_micro_units=destination.amount_micro_units,
                    )
                )
            tx = Transaction(
                tx_id=_tx_id("conf_settle", event_id),
                event_id=event_id,
                created_at=_utc_now(),
                description=f"Settle confidential job reservation {ref}",
                postings=tuple(postings),
            )
            self._record_transaction(tx)
            return ConfidentialCreditSettlement(
                reservation=self._reservation_from_transaction(
                    owner_id=owner,
                    reservation_id=ref,
                    tx=reservation.reserve_transaction,
                ),
                transaction=tx,
                charged_micro_units=actual_amount_micro_units,
                refunded_micro_units=reservation.amount_micro_units - actual_amount_micro_units,
                spent_earned_micro_units=spent["earned"],
                spent_purchased_micro_units=spent["purchased"],
                spent_promo_micro_units=spent["promo"],
            )

    def _settlement_result_from_transaction(
        self,
        *,
        reservation: ConfidentialCreditReservation,
        tx: Transaction,
        actual_amount_micro_units: int,
        destinations: tuple[CreditDestination, ...],
    ) -> ConfidentialCreditSettlement:
        destination_credit = sum(
            posting.credit_micro_units
            for posting in tx.postings
            if any(
                posting.account_id == destination.account_id
                and posting.account_type == destination.account_type
                for destination in destinations
            )
        )
        if destination_credit != actual_amount_micro_units:
            raise BillingError("confidential settlement retry does not match recorded charge")
        spent = {bucket: 0 for bucket in SPEND_ORDER}
        for bucket, reserved_amount in reservation.allocations:
            refunded = sum(
                posting.credit_micro_units
                for posting in tx.postings
                if posting.account_id == owner_bucket_account(reservation.owner_id, bucket)
            )
            if refunded > reserved_amount:
                raise BillingError("confidential settlement refund is inconsistent")
            spent[bucket] = reserved_amount - refunded
        return ConfidentialCreditSettlement(
            reservation=self._reservation_from_transaction(
                owner_id=reservation.owner_id,
                reservation_id=reservation.reservation_id,
                tx=reservation.reserve_transaction,
            ),
            transaction=tx,
            charged_micro_units=actual_amount_micro_units,
            refunded_micro_units=reservation.amount_micro_units - actual_amount_micro_units,
            spent_earned_micro_units=spent["earned"],
            spent_purchased_micro_units=spent["purchased"],
            spent_promo_micro_units=spent["promo"],
        )
