"""Hardened runtime policy for owner-level Stripe settlement.

This layer tightens recovery/idempotency semantics around the lower-level owner
settlement primitives:
- an explicit withdrawal request is never silently reduced to the current balance;
- a deterministic settlement reference cannot reopen a completed settlement;
- crash-after-reserve and crash-after-finalize are replay safe;
- an ambiguous Stripe timeout cannot be cancelled back into spendable earned credit.
"""
from __future__ import annotations

import hashlib
import secrets
import time

from services.billing.accounting import AccountingStoreError, SettlementRecord, utc_now
from services.billing.ledger import (
    BillingError,
    DuplicateEventError,
    InsufficientBalanceError,
    MICRO_UNIT_SCALE,
    MINIMUM_PAYOUT_MICRO_UNITS,
)
from services.billing.owner_settlement import (
    CENT_MICRO_UNITS,
    OwnerSettlementExecutor,
    _event_tx_id,
)


_IN_FLIGHT = {"reserving", "pending", "pending_retry", "transferred"}
_TERMINAL = {"completed", "cancelled"}


class RobustOwnerSettlementExecutor(OwnerSettlementExecutor):
    """Production-safe owner settlement coordinator with strict replay semantics."""

    @staticmethod
    def _settlement_id(reference: str | None) -> str:
        ref = str(reference or "").strip()
        if ref:
            digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:20]
            return f"settle_owner_{digest}"
        return f"settle_owner_{int(time.time())}_{secrets.token_hex(6)}"

    def _validate_existing_reference(
        self,
        *,
        existing: SettlementRecord,
        owner_id: str,
        requested_amount_micro_units: int | None,
    ) -> SettlementRecord:
        if existing.account_kind != "owner" or existing.account_id != owner_id:
            raise AccountingStoreError(
                "settlement reference is already bound to another payout subject"
            )
        if requested_amount_micro_units is not None:
            quantized = self._quantize_amount(int(requested_amount_micro_units))
            if quantized != existing.amount_micro_units:
                raise AccountingStoreError(
                    "settlement reference was already used with a different amount"
                )
        if existing.status == "completed":
            return existing
        if existing.status in _IN_FLIGHT:
            return self._resume(existing)
        raise AccountingStoreError(
            f"settlement reference cannot be reused from terminal status {existing.status!r}"
        )

    def run_owner_settlement(
        self,
        *,
        owner_id: str,
        amount_micro_units: int | None = None,
        settlement_reference: str | None = None,
    ) -> SettlementRecord:
        owner = str(owner_id or "").strip()
        if not owner:
            raise AccountingStoreError("owner_id is required")

        explicit_amount: int | None = None
        if amount_micro_units is not None:
            explicit_amount = int(amount_micro_units)
            if explicit_amount <= 0:
                raise BillingError("withdrawal amount must be positive")

        reference = str(settlement_reference or "").strip() or None
        settlement_id = self._settlement_id(reference)
        if reference:
            existing_by_reference = self.account_store.get_settlement(settlement_id)
            if existing_by_reference is not None:
                return self._validate_existing_reference(
                    existing=existing_by_reference,
                    owner_id=owner,
                    requested_amount_micro_units=explicit_amount,
                )

        existing = self._inflight_for_owner(owner)
        if existing:
            return self._resume(existing)

        profile = self.refresh_owner_connect_status(owner_id=owner)
        if not profile.payouts_enabled:
            raise AccountingStoreError(f"owner {owner} Stripe payouts are not enabled")

        withdrawable = self.ledger.owner_withdrawable_micro_units(owner)
        if explicit_amount is not None and explicit_amount > withdrawable:
            raise InsufficientBalanceError(
                f"owner {owner} withdrawable earned balance ({withdrawable}) "
                f"is below requested withdrawal ({explicit_amount})"
            )
        requested = withdrawable if explicit_amount is None else explicit_amount
        amount = self._quantize_amount(requested)
        if amount < MINIMUM_PAYOUT_MICRO_UNITS:
            raise BillingError(
                f"owner withdrawable amount {amount} below minimum payout threshold "
                f"{MINIMUM_PAYOUT_MICRO_UNITS}"
            )

        now = utc_now()
        record = SettlementRecord(
            settlement_id=settlement_id,
            account_kind="owner",
            account_id=owner,
            amount_micro_units=amount,
            amount_usd=round(amount / MICRO_UNIT_SCALE, 4),
            currency="usd",
            stripe_connected_account_id=profile.stripe_connected_account_id,
            destination=profile.stripe_connected_account_id,
            status="reserving",
            created_at=now,
            updated_at=now,
        )
        self.account_store.upsert_settlement(record)
        return self._resume(record)

    def _resume(self, record: SettlementRecord) -> SettlementRecord:
        if record.account_kind != "owner":
            raise AccountingStoreError("cannot resume non-owner settlement")
        owner = record.account_id
        amount = int(record.amount_micro_units)
        profile = self.profile_store.get(owner)
        if not profile or profile.stripe_connected_account_id != record.stripe_connected_account_id:
            raise AccountingStoreError("owner payout profile does not match pending settlement")

        current = self.account_store.get_settlement(record.settlement_id) or record
        if current.status == "completed":
            return current
        if current.status not in _IN_FLIGHT:
            raise AccountingStoreError(
                f"owner settlement {current.settlement_id} is not resumable from {current.status!r}"
            )

        if current.status == "reserving":
            try:
                reserve_tx = self.ledger.reserve_owner_withdrawal(
                    owner_id=owner,
                    amount_micro_units=amount,
                    settlement_reference=current.settlement_id,
                )
                reserve_tx_id = reserve_tx.tx_id
            except DuplicateEventError:
                if self.ledger.owner_withdrawal_pending_micro_units(owner) < amount:
                    raise BillingError(
                        "withdrawal reservation event exists without matching pending liability"
                    )
                reserve_event = f"owner-withdrawal-reserve:{current.settlement_id}"
                reserve_tx_id = _event_tx_id("owner_withdraw_reserve", reserve_event)
            current = self.account_store.upsert_settlement(
                SettlementRecord(
                    **{
                        **current.to_dict(),
                        "ledger_tx_id": reserve_tx_id,
                        "status": "pending",
                        "updated_at": utc_now(),
                    }
                )
            )

        if current.status in {"pending", "pending_retry"}:
            try:
                transfer_id = self.stripe.transfer(
                    settlement_id=current.settlement_id,
                    owner_id=owner,
                    amount_micro_units=amount,
                    stripe_connected_account_id=current.stripe_connected_account_id,
                    currency=current.currency,
                )
            except Exception as exc:
                # This includes transport/API exceptions whose remote outcome may be
                # unknown. The reservation is deliberately retained for a same-id retry.
                return self.account_store.upsert_settlement(
                    SettlementRecord(
                        **{
                            **current.to_dict(),
                            "status": "pending_retry",
                            "error": str(exc)[:1000],
                            "updated_at": utc_now(),
                        }
                    )
                )
            current = self.account_store.upsert_settlement(
                SettlementRecord(
                    **{
                        **current.to_dict(),
                        "stripe_transfer_id": transfer_id,
                        "status": "transferred",
                        "error": "",
                        "updated_at": utc_now(),
                    }
                )
            )

        if current.status == "transferred":
            try:
                final_tx = self.ledger.finalize_owner_withdrawal(
                    owner_id=owner,
                    amount_micro_units=amount,
                    settlement_reference=current.settlement_id,
                )
                final_tx_id = final_tx.tx_id
            except DuplicateEventError:
                # Crash-after-finalize-before-SQL-state-update: reconstruct the
                # deterministic journal id instead of preserving the reserve tx id.
                final_event = f"owner-withdrawal-finalize:{current.settlement_id}"
                final_tx_id = _event_tx_id("owner_withdraw_final", final_event)
                if self.ledger.owner_withdrawal_pending_micro_units(owner) >= amount:
                    raise BillingError(
                        "finalization event exists but pending withdrawal liability remains"
                    )
            current = self.account_store.upsert_settlement(
                SettlementRecord(
                    **{
                        **current.to_dict(),
                        "ledger_tx_id": final_tx_id,
                        "status": "completed",
                        "error": "",
                        "updated_at": utc_now(),
                    }
                )
            )
        return current

    def cancel_untransferred_settlement(self, *, settlement_id: str) -> SettlementRecord:
        record = self.account_store.get_settlement(settlement_id)
        if not record or record.account_kind != "owner":
            raise AccountingStoreError("owner settlement not found")
        if record.status == "pending_retry":
            raise AccountingStoreError(
                "cannot cancel pending_retry: Stripe transfer outcome may be ambiguous"
            )
        if record.stripe_transfer_id or record.status in {"transferred", "completed"}:
            raise AccountingStoreError("cannot cancel a settlement after Stripe transfer")
        if record.status == "cancelled":
            return record
        if record.status not in {"reserving", "pending"}:
            raise AccountingStoreError(
                f"cannot cancel owner settlement from status {record.status!r}"
            )

        pending = self.ledger.owner_withdrawal_pending_micro_units(record.account_id)
        if pending >= record.amount_micro_units:
            try:
                self.ledger.cancel_owner_withdrawal(
                    owner_id=record.account_id,
                    amount_micro_units=record.amount_micro_units,
                    settlement_reference=record.settlement_id,
                )
            except DuplicateEventError:
                pass
        elif record.status == "pending":
            raise BillingError("pending settlement has no matching withdrawal liability")

        updated = SettlementRecord(
            **{
                **record.to_dict(),
                "status": "cancelled",
                "error": "",
                "updated_at": utc_now(),
            }
        )
        return self.account_store.upsert_settlement(updated)
