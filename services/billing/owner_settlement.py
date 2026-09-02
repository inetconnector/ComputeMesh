"""Owner-level Stripe Connect onboarding and crash-safe earned-credit settlement.

Unified owner balances aggregate earnings across all provider nodes owned by one
principal. This module keeps payout identity and payout state owner-scoped and
never treats purchased or promo credits as withdrawable.

The payout journal is deliberately two-phase:
1. move earned liability into a durable owner withdrawal-pending liability;
2. perform an idempotent Stripe transfer;
3. extinguish the pending liability against the payment-gateway asset.

Ambiguous Stripe/network failures do not release the reserved liability. Retrying
with the same settlement id is safe because the Stripe transfer uses an idempotency
key. This prevents a timeout after a successful remote transfer from creating a
second spendable copy of the money locally.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import secrets
import sqlite3
import time
from typing import Any

from services.billing.accounting import AccountingStore, AccountingStoreError, SettlementRecord, utc_now
from services.billing.ledger import (
    BillingError,
    DuplicateEventError,
    InsufficientBalanceError,
    MICRO_UNIT_SCALE,
    MINIMUM_PAYOUT_MICRO_UNITS,
    Posting,
    Transaction,
)
from services.billing.owner_credits import (
    OWNER_EARNED,
    PAYMENT_GATEWAY_ESCROW,
    owner_bucket_account,
)
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.stripe_connect import AccountLinkResult, ConnectedAccountResult, StripeConnectService
from services.billing.stripe_integration import StripeIntegrationError, _stripe_get

OWNER_WITHDRAWAL_PENDING = "liability:owner_withdrawal_pending"
CENT_MICRO_UNITS = MICRO_UNIT_SCALE // 100


@dataclass(frozen=True)
class OwnerPayoutProfile:
    owner_id: str
    stripe_connected_account_id: str = ""
    stripe_onboarding_status: str = "not_started"
    payouts_enabled: bool = False
    details_submitted: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OwnerPayoutProfileStore:
    """Owner-scoped payout identity stored beside operational settlement state."""

    def __init__(self, accounting_store: AccountingStore) -> None:
        self.accounting_store = accounting_store
        self.storage_path = accounting_store.storage_path
        self._init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.storage_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS owner_payout_profiles (
                    owner_id TEXT PRIMARY KEY,
                    stripe_connected_account_id TEXT NOT NULL DEFAULT '',
                    stripe_onboarding_status TEXT NOT NULL DEFAULT 'not_started',
                    payouts_enabled INTEGER NOT NULL DEFAULT 0,
                    details_submitted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_owner_payout_stripe_account
                ON owner_payout_profiles(stripe_connected_account_id)
                WHERE stripe_connected_account_id <> ''
                """
            )

    def ensure(self, owner_id: str) -> OwnerPayoutProfile:
        owner = str(owner_id or "").strip()
        if not owner:
            raise AccountingStoreError("owner_id is required")
        now = utc_now()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO owner_payout_profiles(owner_id, created_at, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(owner_id) DO NOTHING
                """,
                (owner, now, now),
            )
        profile = self.get(owner)
        assert profile is not None
        return profile

    def get(self, owner_id: str) -> OwnerPayoutProfile | None:
        owner = str(owner_id or "").strip()
        if not owner:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM owner_payout_profiles WHERE owner_id = ?",
                (owner,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def attach_stripe_account(
        self,
        *,
        owner_id: str,
        stripe_connected_account_id: str,
        onboarding_status: str = "account_created",
    ) -> OwnerPayoutProfile:
        profile = self.ensure(owner_id)
        account_id = str(stripe_connected_account_id or "").strip()
        if not account_id:
            raise AccountingStoreError("stripe_connected_account_id is required")
        with self._connection() as conn:
            try:
                conn.execute(
                    """
                    UPDATE owner_payout_profiles
                    SET stripe_connected_account_id = ?, stripe_onboarding_status = ?, updated_at = ?
                    WHERE owner_id = ?
                    """,
                    (account_id, onboarding_status, utc_now(), profile.owner_id),
                )
            except sqlite3.IntegrityError as exc:
                raise AccountingStoreError(
                    "Stripe connected account is already attached to another owner"
                ) from exc
        result = self.get(profile.owner_id)
        assert result is not None
        return result

    def update_status(
        self,
        *,
        owner_id: str,
        onboarding_status: str,
        payouts_enabled: bool,
        details_submitted: bool,
    ) -> OwnerPayoutProfile:
        profile = self.ensure(owner_id)
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE owner_payout_profiles
                SET stripe_onboarding_status = ?, payouts_enabled = ?,
                    details_submitted = ?, updated_at = ?
                WHERE owner_id = ?
                """,
                (
                    str(onboarding_status or "not_started"),
                    int(bool(payouts_enabled)),
                    int(bool(details_submitted)),
                    utc_now(),
                    profile.owner_id,
                ),
            )
        result = self.get(profile.owner_id)
        assert result is not None
        return result

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OwnerPayoutProfile:
        return OwnerPayoutProfile(
            owner_id=str(row["owner_id"]),
            stripe_connected_account_id=str(row["stripe_connected_account_id"]),
            stripe_onboarding_status=str(row["stripe_onboarding_status"]),
            payouts_enabled=bool(row["payouts_enabled"]),
            details_submitted=bool(row["details_submitted"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _event_tx_id(prefix: str, event_id: str) -> str:
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]
    return f"tx_{prefix}_{digest}"


def _pending_account(owner_id: str) -> str:
    owner = str(owner_id or "").strip()
    if not owner:
        raise BillingError("owner_id is required")
    return f"owner:{owner}:withdrawal_pending"


class PayoutCapableOwnerLedger(GatewayOwnerCreditLedger):
    """Unified owner ledger with durable earned-only payout reservations."""

    def owner_withdrawal_pending_micro_units(self, owner_id: str) -> int:
        return self.get_balance(_pending_account(owner_id))

    def reserve_owner_withdrawal(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        settlement_reference: str,
    ) -> Transaction:
        owner = str(owner_id or "").strip()
        reference = str(settlement_reference or "").strip()
        if not owner or not reference:
            raise BillingError("owner_id and settlement_reference are required")
        if amount_micro_units <= 0:
            raise BillingError("withdrawal amount must be positive")
        with self._lock:
            withdrawable = self.owner_withdrawable_micro_units(owner)
            if withdrawable < amount_micro_units:
                raise InsufficientBalanceError(
                    f"owner {owner} withdrawable earned balance ({withdrawable}) "
                    f"is below requested withdrawal ({amount_micro_units})"
                )
            event_id = f"owner-withdrawal-reserve:{reference}"
            self._ensure_new_event(event_id)
            tx = Transaction(
                tx_id=_event_tx_id("owner_withdraw_reserve", event_id),
                event_id=event_id,
                created_at=utc_now(),
                description=f"Reserve owner earned credits for Stripe settlement {reference}",
                postings=(
                    Posting(
                        account_id=owner_bucket_account(owner, "earned"),
                        account_type=OWNER_EARNED,
                        debit_micro_units=amount_micro_units,
                    ),
                    Posting(
                        account_id=_pending_account(owner),
                        account_type=OWNER_WITHDRAWAL_PENDING,
                        credit_micro_units=amount_micro_units,
                    ),
                ),
            )
            self._record_transaction(tx)
            return tx

    def finalize_owner_withdrawal(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        settlement_reference: str,
    ) -> Transaction:
        owner = str(owner_id or "").strip()
        reference = str(settlement_reference or "").strip()
        if amount_micro_units <= 0:
            raise BillingError("withdrawal amount must be positive")
        with self._lock:
            pending = self.owner_withdrawal_pending_micro_units(owner)
            if pending < amount_micro_units:
                raise BillingError(
                    f"owner {owner} pending withdrawal balance ({pending}) is below "
                    f"settlement amount ({amount_micro_units})"
                )
            event_id = f"owner-withdrawal-finalize:{reference}"
            self._ensure_new_event(event_id)
            tx = Transaction(
                tx_id=_event_tx_id("owner_withdraw_final", event_id),
                event_id=event_id,
                created_at=utc_now(),
                description=f"Finalize owner Stripe settlement {reference}",
                postings=(
                    Posting(
                        account_id=_pending_account(owner),
                        account_type=OWNER_WITHDRAWAL_PENDING,
                        debit_micro_units=amount_micro_units,
                    ),
                    Posting(
                        account_id="gateway:escrow",
                        account_type=PAYMENT_GATEWAY_ESCROW,
                        credit_micro_units=amount_micro_units,
                    ),
                ),
            )
            self._record_transaction(tx)
            return tx

    def cancel_owner_withdrawal(
        self,
        *,
        owner_id: str,
        amount_micro_units: int,
        settlement_reference: str,
    ) -> Transaction:
        owner = str(owner_id or "").strip()
        reference = str(settlement_reference or "").strip()
        if amount_micro_units <= 0:
            raise BillingError("withdrawal amount must be positive")
        with self._lock:
            pending = self.owner_withdrawal_pending_micro_units(owner)
            if pending < amount_micro_units:
                raise BillingError("insufficient pending withdrawal balance to cancel")
            event_id = f"owner-withdrawal-cancel:{reference}"
            self._ensure_new_event(event_id)
            tx = Transaction(
                tx_id=_event_tx_id("owner_withdraw_cancel", event_id),
                event_id=event_id,
                created_at=utc_now(),
                description=f"Cancel owner Stripe settlement reservation {reference}",
                postings=(
                    Posting(
                        account_id=_pending_account(owner),
                        account_type=OWNER_WITHDRAWAL_PENDING,
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


class OwnerStripeConnectAdapter:
    """Owner-scoped use of Stripe Connect without per-node payout identity."""

    def __init__(self, base: StripeConnectService) -> None:
        self.base = base

    def create_connected_account(
        self,
        *,
        owner_id: str,
        email: str = "",
        country: str = "DE",
    ) -> ConnectedAccountResult:
        self.base.require_configured()
        subject = f"owner:{owner_id}"
        if self.base.connect_api_mode == "v2":
            payload: dict[str, Any] = {
                "display_name": f"ComputeMesh owner {owner_id}",
                "dashboard": "express",
                "identity": {"country": country.lower()},
                "defaults": {
                    "responsibilities": {
                        "fees_collector": "application",
                        "losses_collector": "application",
                    }
                },
                "configuration": {
                    "recipient": {
                        "capabilities": {
                            "stripe_balance": {"stripe_transfers": {"requested": True}}
                        }
                    }
                },
                "metadata": {
                    "owner_id": owner_id,
                    "account_kind": "owner",
                    "product": "computemesh_owner_payouts",
                },
                "include": ["configuration.recipient", "identity", "requirements"],
            }
            if email:
                payload["contact_email"] = email
            account = self.base._stripe_v2_request("POST", "/v2/core/accounts", payload=payload)
            return self.base._account_result_v2(provider_node_id=subject, account=account)

        params: dict[str, Any] = {
            "type": "express",
            "country": country.upper(),
            "capabilities": {"transfers": {"requested": True}},
            "metadata": {
                "owner_id": owner_id,
                "account_kind": "owner",
                "product": "computemesh_owner_payouts",
            },
        }
        if email:
            params["email"] = email
        try:
            account = self.base.stripe_client.Account.create(**params)
        except Exception as exc:
            if self.base._should_fallback_to_v2(exc):
                previous = self.base.connect_api_mode
                try:
                    self.base.connect_api_mode = "v2"
                    return self.create_connected_account(
                        owner_id=owner_id,
                        email=email,
                        country=country,
                    )
                finally:
                    self.base.connect_api_mode = previous
            raise StripeIntegrationError(
                f"Stripe owner connected account creation failed: {exc}"
            ) from exc
        return self.base._account_result(provider_node_id=subject, account=account)

    def retrieve_connected_account(
        self,
        *,
        owner_id: str,
        stripe_connected_account_id: str,
    ) -> ConnectedAccountResult:
        return self.base.retrieve_connected_account(
            provider_node_id=f"owner:{owner_id}",
            stripe_connected_account_id=stripe_connected_account_id,
        )

    def create_account_link(
        self,
        *,
        stripe_connected_account_id: str,
        refresh_url: str,
        return_url: str,
    ) -> AccountLinkResult:
        return self.base.create_account_link(
            stripe_connected_account_id=stripe_connected_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
        )

    def transfer(
        self,
        *,
        settlement_id: str,
        owner_id: str,
        amount_micro_units: int,
        stripe_connected_account_id: str,
        currency: str = "usd",
    ) -> str:
        self.base.require_configured()
        if amount_micro_units <= 0 or amount_micro_units % CENT_MICRO_UNITS:
            raise StripeIntegrationError(
                "owner transfer amount must be positive and aligned to Stripe cent precision"
            )
        amount_cents = amount_micro_units // CENT_MICRO_UNITS
        metadata = {
            "settlement_id": settlement_id,
            "owner_id": owner_id,
            "account_kind": "owner",
            "amount_micro_units": str(amount_micro_units),
            "product": "computemesh_owner_settlement",
        }
        try:
            transfer = self.base.stripe_client.Transfer.create(
                amount=amount_cents,
                currency=currency.lower(),
                destination=stripe_connected_account_id,
                transfer_group=settlement_id,
                metadata=metadata,
                idempotency_key=f"computemesh-owner:{settlement_id}",
            )
        except TypeError:
            transfer = self.base.stripe_client.Transfer.create(
                amount=amount_cents,
                currency=currency.lower(),
                destination=stripe_connected_account_id,
                transfer_group=settlement_id,
                metadata=metadata,
            )
        except Exception as exc:
            raise StripeIntegrationError(f"Stripe owner transfer failed: {exc}") from exc
        transfer_id = str(_stripe_get(transfer, "id", ""))
        if not transfer_id:
            raise StripeIntegrationError("Stripe owner transfer did not return an id")
        return transfer_id


class OwnerSettlementExecutor:
    """Coordinates owner-level Connect onboarding and earned-only withdrawals."""

    def __init__(
        self,
        *,
        ledger: PayoutCapableOwnerLedger,
        account_store: AccountingStore,
        stripe_connect: StripeConnectService,
    ) -> None:
        self.ledger = ledger
        self.account_store = account_store
        self.profile_store = OwnerPayoutProfileStore(account_store)
        self.stripe = OwnerStripeConnectAdapter(stripe_connect)

    def create_or_refresh_owner_connect_account(
        self,
        *,
        owner_id: str,
        email: str = "",
        country: str = "DE",
    ) -> OwnerPayoutProfile:
        profile = self.profile_store.ensure(owner_id)
        if profile.stripe_connected_account_id:
            status = self.stripe.retrieve_connected_account(
                owner_id=owner_id,
                stripe_connected_account_id=profile.stripe_connected_account_id,
            )
        else:
            status = self.stripe.create_connected_account(
                owner_id=owner_id,
                email=email,
                country=country,
            )
            profile = self.profile_store.attach_stripe_account(
                owner_id=owner_id,
                stripe_connected_account_id=status.stripe_connected_account_id,
                onboarding_status=status.onboarding_status,
            )
        return self.profile_store.update_status(
            owner_id=owner_id,
            onboarding_status=status.onboarding_status,
            payouts_enabled=status.payouts_enabled,
            details_submitted=status.details_submitted,
        )

    def create_owner_onboarding_link(
        self,
        *,
        owner_id: str,
        refresh_url: str,
        return_url: str,
    ) -> AccountLinkResult:
        profile = self.profile_store.get(owner_id)
        if not profile or not profile.stripe_connected_account_id:
            raise AccountingStoreError(f"owner {owner_id} has no Stripe connected account")
        return self.stripe.create_account_link(
            stripe_connected_account_id=profile.stripe_connected_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
        )

    def refresh_owner_connect_status(self, *, owner_id: str) -> OwnerPayoutProfile:
        profile = self.profile_store.get(owner_id)
        if not profile or not profile.stripe_connected_account_id:
            raise AccountingStoreError(f"owner {owner_id} has no Stripe connected account")
        status = self.stripe.retrieve_connected_account(
            owner_id=owner_id,
            stripe_connected_account_id=profile.stripe_connected_account_id,
        )
        return self.profile_store.update_status(
            owner_id=owner_id,
            onboarding_status=status.onboarding_status,
            payouts_enabled=status.payouts_enabled,
            details_submitted=status.details_submitted,
        )

    def _inflight_for_owner(self, owner_id: str) -> SettlementRecord | None:
        for status in ("transferred", "pending_retry", "pending", "reserving"):
            for record in self.account_store.list_settlements(status=status, limit=500):
                if record.account_kind == "owner" and record.account_id == owner_id:
                    return record
        return None

    def _quantize_amount(self, amount_micro_units: int) -> int:
        return max(0, int(amount_micro_units) // CENT_MICRO_UNITS * CENT_MICRO_UNITS)

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

        existing = self._inflight_for_owner(owner)
        if existing:
            return self._resume(existing)

        profile = self.refresh_owner_connect_status(owner_id=owner)
        if not profile.payouts_enabled:
            raise AccountingStoreError(f"owner {owner} Stripe payouts are not enabled")

        withdrawable = self.ledger.owner_withdrawable_micro_units(owner)
        requested = withdrawable if amount_micro_units is None else min(
            int(amount_micro_units), withdrawable
        )
        amount = self._quantize_amount(requested)
        if amount < MINIMUM_PAYOUT_MICRO_UNITS:
            raise BillingError(
                f"owner withdrawable amount {amount} below minimum payout threshold "
                f"{MINIMUM_PAYOUT_MICRO_UNITS}"
            )

        reference = str(settlement_reference or "").strip()
        if reference:
            settlement_id = f"settle_owner_{hashlib.sha256(reference.encode('utf-8')).hexdigest()[:20]}"
        else:
            settlement_id = f"settle_owner_{int(time.time())}_{secrets.token_hex(6)}"
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
                    raise BillingError("withdrawal reservation event exists without pending liability")
                reserve_tx_id = current.ledger_tx_id
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
            except StripeIntegrationError as exc:
                # Ambiguous remote failures stay reserved. Retrying the same settlement
                # id is safe through Stripe's idempotency key.
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
                final_tx_id = current.ledger_tx_id
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
        if record.stripe_transfer_id or record.status in {"transferred", "completed"}:
            raise AccountingStoreError("cannot cancel a settlement after Stripe transfer")
        if record.status == "reserving":
            updated = SettlementRecord(
                **{**record.to_dict(), "status": "cancelled", "updated_at": utc_now()}
            )
            return self.account_store.upsert_settlement(updated)
        self.ledger.cancel_owner_withdrawal(
            owner_id=record.account_id,
            amount_micro_units=record.amount_micro_units,
            settlement_reference=record.settlement_id,
        )
        updated = SettlementRecord(
            **{
                **record.to_dict(),
                "status": "cancelled",
                "error": "",
                "updated_at": utc_now(),
            }
        )
        return self.account_store.upsert_settlement(updated)
