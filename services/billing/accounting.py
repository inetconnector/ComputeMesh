#!/usr/bin/env python3
"""Durable billing account, webhook inbox, and settlement state.

The append-only ledger remains the financial journal. This module stores the
operational records required to run the journal professionally: provider payout
configuration, Stripe webhook event idempotency, and external settlement state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


SCHEMA_VERSION = 1


class AccountingStoreError(Exception):
    """Raised when account or settlement state is invalid."""


@dataclass(frozen=True)
class ProviderAccount:
    provider_node_id: str
    ledger_account_id: str
    display_name: str = ""
    payout_wallet_address: str = ""
    stripe_connected_account_id: str = ""
    stripe_onboarding_status: str = "not_started"
    charges_enabled: bool = False
    payouts_enabled: bool = False
    details_submitted: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SettlementRecord:
    settlement_id: str
    account_kind: str
    account_id: str
    amount_micro_units: int
    amount_usd: float
    currency: str = "usd"
    ledger_tx_id: str = ""
    stripe_transfer_id: str = ""
    stripe_connected_account_id: str = ""
    destination: str = ""
    status: str = "pending"
    error: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AccountingStore:
    """SQLite-backed operational billing store."""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.storage_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_accounts (
                    provider_node_id TEXT PRIMARY KEY,
                    ledger_account_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    payout_wallet_address TEXT NOT NULL DEFAULT '',
                    stripe_connected_account_id TEXT NOT NULL DEFAULT '',
                    stripe_onboarding_status TEXT NOT NULL DEFAULT 'not_started',
                    charges_enabled INTEGER NOT NULL DEFAULT 0,
                    payouts_enabled INTEGER NOT NULL DEFAULT 0,
                    details_submitted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stripe_webhook_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    processing_started_at TEXT NOT NULL DEFAULT '',
                    processed_at TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settlement_records (
                    settlement_id TEXT PRIMARY KEY,
                    account_kind TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    amount_micro_units INTEGER NOT NULL,
                    amount_usd REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'usd',
                    ledger_tx_id TEXT NOT NULL DEFAULT '',
                    stripe_transfer_id TEXT NOT NULL DEFAULT '',
                    stripe_connected_account_id TEXT NOT NULL DEFAULT '',
                    destination TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(settlement_records)").fetchall()
            }
            if "currency" not in columns:
                conn.execute("ALTER TABLE settlement_records ADD COLUMN currency TEXT NOT NULL DEFAULT 'usd'")

    def upsert_provider(
        self,
        *,
        provider_node_id: str,
        display_name: str = "",
        payout_wallet_address: str = "",
    ) -> ProviderAccount:
        provider_node_id = provider_node_id.strip()
        if not provider_node_id:
            raise AccountingStoreError("provider_node_id is required")
        now = utc_now()
        ledger_account_id = f"provider:{provider_node_id}"
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM provider_accounts WHERE provider_node_id = ?",
                (provider_node_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE provider_accounts
                    SET display_name = COALESCE(NULLIF(?, ''), display_name),
                        payout_wallet_address = COALESCE(NULLIF(?, ''), payout_wallet_address),
                        updated_at = ?
                    WHERE provider_node_id = ?
                    """,
                    (display_name.strip(), payout_wallet_address.strip(), now, provider_node_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO provider_accounts(
                        provider_node_id, ledger_account_id, display_name,
                        payout_wallet_address, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provider_node_id,
                        ledger_account_id,
                        display_name.strip(),
                        payout_wallet_address.strip(),
                        now,
                        now,
                    ),
                )
        return self.get_provider(provider_node_id)  # type: ignore[return-value]

    def attach_stripe_account(
        self,
        *,
        provider_node_id: str,
        stripe_connected_account_id: str,
        onboarding_status: str = "account_created",
    ) -> ProviderAccount:
        provider = self.upsert_provider(provider_node_id=provider_node_id)
        now = utc_now()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE provider_accounts
                SET stripe_connected_account_id = ?,
                    stripe_onboarding_status = ?,
                    updated_at = ?
                WHERE provider_node_id = ?
                """,
                (stripe_connected_account_id.strip(), onboarding_status, now, provider.provider_node_id),
            )
        return self.get_provider(provider.provider_node_id)  # type: ignore[return-value]

    def update_stripe_account_status(
        self,
        *,
        provider_node_id: str,
        onboarding_status: str,
        charges_enabled: bool,
        payouts_enabled: bool,
        details_submitted: bool,
    ) -> ProviderAccount:
        provider = self.get_provider(provider_node_id)
        if not provider:
            raise AccountingStoreError(f"unknown provider {provider_node_id}")
        now = utc_now()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE provider_accounts
                SET stripe_onboarding_status = ?,
                    charges_enabled = ?,
                    payouts_enabled = ?,
                    details_submitted = ?,
                    updated_at = ?
                WHERE provider_node_id = ?
                """,
                (
                    onboarding_status,
                    int(charges_enabled),
                    int(payouts_enabled),
                    int(details_submitted),
                    now,
                    provider_node_id,
                ),
            )
        return self.get_provider(provider_node_id)  # type: ignore[return-value]

    def update_stripe_account_status_by_account_id(
        self,
        *,
        stripe_connected_account_id: str,
        provider_node_id_hint: str = "",
        onboarding_status: str,
        charges_enabled: bool,
        payouts_enabled: bool,
        details_submitted: bool,
    ) -> ProviderAccount | None:
        provider = self.get_provider_by_stripe_account_id(stripe_connected_account_id)
        if not provider and provider_node_id_hint:
            existing = self.get_provider(provider_node_id_hint)
            if existing:
                provider = self.attach_stripe_account(
                    provider_node_id=provider_node_id_hint,
                    stripe_connected_account_id=stripe_connected_account_id,
                    onboarding_status=onboarding_status,
                )
        if not provider:
            return None
        return self.update_stripe_account_status(
            provider_node_id=provider.provider_node_id,
            onboarding_status=onboarding_status,
            charges_enabled=charges_enabled,
            payouts_enabled=payouts_enabled,
            details_submitted=details_submitted,
        )

    def get_provider(self, provider_node_id: str) -> ProviderAccount | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_accounts WHERE provider_node_id = ?",
                (provider_node_id.strip(),),
            ).fetchone()
        return self._provider_from_row(row) if row else None

    def get_provider_by_stripe_account_id(self, stripe_connected_account_id: str) -> ProviderAccount | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM provider_accounts WHERE stripe_connected_account_id = ?",
                (stripe_connected_account_id.strip(),),
            ).fetchone()
        return self._provider_from_row(row) if row else None

    def list_providers(self) -> list[ProviderAccount]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM provider_accounts ORDER BY provider_node_id"
            ).fetchall()
        return [self._provider_from_row(row) for row in rows]

    def begin_webhook_event(self, *, event_id: str, event_type: str, payload: dict[str, Any]) -> str:
        """Insert or mark a Stripe webhook event for processing.

        Returns ``new``, ``retry`` or ``already_processed``.
        """
        event_id = event_id.strip()
        if not event_id:
            return "untracked"
        now = utc_now()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._connection() as conn:
            row = conn.execute(
                "SELECT status FROM stripe_webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row and row["status"] == "processed":
                return "already_processed"
            if row:
                conn.execute(
                    """
                    UPDATE stripe_webhook_events
                    SET event_type = ?, payload_json = ?, status = 'processing',
                        processing_started_at = ?, error = ''
                    WHERE event_id = ?
                    """,
                    (event_type, payload_json, now, event_id),
                )
                return "retry"
            conn.execute(
                """
                INSERT INTO stripe_webhook_events(
                    event_id, event_type, payload_json, status,
                    received_at, processing_started_at
                ) VALUES (?, ?, ?, 'processing', ?, ?)
                """,
                (event_id, event_type, payload_json, now, now),
            )
        return "new"

    def mark_webhook_processed(self, event_id: str) -> None:
        if not event_id:
            return
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE stripe_webhook_events
                SET status = 'processed', processed_at = ?, error = ''
                WHERE event_id = ?
                """,
                (utc_now(), event_id),
            )

    def mark_webhook_failed(self, event_id: str, error: str) -> None:
        if not event_id:
            return
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE stripe_webhook_events
                SET status = 'failed', error = ?
                WHERE event_id = ?
                """,
                (error[:1000], event_id),
            )

    def upsert_settlement(self, record: SettlementRecord) -> SettlementRecord:
        if not record.settlement_id:
            raise AccountingStoreError("settlement_id is required")
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO settlement_records(
                    settlement_id, account_kind, account_id, amount_micro_units,
                    amount_usd, currency, ledger_tx_id, stripe_transfer_id,
                    stripe_connected_account_id, destination, status, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(settlement_id) DO UPDATE SET
                    currency = excluded.currency,
                    ledger_tx_id = excluded.ledger_tx_id,
                    stripe_transfer_id = excluded.stripe_transfer_id,
                    stripe_connected_account_id = excluded.stripe_connected_account_id,
                    destination = excluded.destination,
                    status = excluded.status,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (
                    record.settlement_id,
                    record.account_kind,
                    record.account_id,
                    record.amount_micro_units,
                    record.amount_usd,
                    record.currency.lower(),
                    record.ledger_tx_id,
                    record.stripe_transfer_id,
                    record.stripe_connected_account_id,
                    record.destination,
                    record.status,
                    record.error,
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def get_settlement(self, settlement_id: str) -> SettlementRecord | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM settlement_records WHERE settlement_id = ?",
                (settlement_id,),
            ).fetchone()
        return self._settlement_from_row(row) if row else None

    def list_settlements(self, *, status: str = "", limit: int = 100) -> list[SettlementRecord]:
        limit = max(1, min(int(limit), 500))
        with self._connection() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM settlement_records
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM settlement_records ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._settlement_from_row(row) for row in rows]

    @staticmethod
    def _provider_from_row(row: sqlite3.Row) -> ProviderAccount:
        return ProviderAccount(
            provider_node_id=row["provider_node_id"],
            ledger_account_id=row["ledger_account_id"],
            display_name=row["display_name"],
            payout_wallet_address=row["payout_wallet_address"],
            stripe_connected_account_id=row["stripe_connected_account_id"],
            stripe_onboarding_status=row["stripe_onboarding_status"],
            charges_enabled=bool(row["charges_enabled"]),
            payouts_enabled=bool(row["payouts_enabled"]),
            details_submitted=bool(row["details_submitted"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _settlement_from_row(row: sqlite3.Row) -> SettlementRecord:
        return SettlementRecord(
            settlement_id=row["settlement_id"],
            account_kind=row["account_kind"],
            account_id=row["account_id"],
            amount_micro_units=int(row["amount_micro_units"]),
            amount_usd=float(row["amount_usd"]),
            currency=row["currency"],
            ledger_tx_id=row["ledger_tx_id"],
            stripe_transfer_id=row["stripe_transfer_id"],
            stripe_connected_account_id=row["stripe_connected_account_id"],
            destination=row["destination"],
            status=row["status"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
