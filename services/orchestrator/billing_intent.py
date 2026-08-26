"""Durable billing intents for verified ComputeMesh executions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import threading
from typing import Iterable

from services.billing.ledger import (
    AccountType,
    DuplicateEventError,
    InsufficientBalanceError,
    Posting,
    Transaction,
)
from services.orchestrator.state_machine import JobState


@dataclass(frozen=True)
class BillingIntent:
    job_id: str
    account_id: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    provider_shares: tuple[tuple[str, float], ...]
    network_fee_bps: int
    prompt_micro_per_token: int
    completion_micro_per_token: int
    total_charge_micro_units: int
    status: str
    created_at: datetime
    recorded_at: datetime | None


class BillingIntentConflict(RuntimeError):
    pass


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class BillingIntentStore:
    """Outbox sharing the durable orchestrator SQLite database."""

    def __init__(self, state_store):
        self.state_store = state_store
        self.path = state_store.path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS billing_intent (
                job_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL CHECK(prompt_tokens >= 0),
                completion_tokens INTEGER NOT NULL CHECK(completion_tokens >= 0),
                provider_shares_json TEXT NOT NULL,
                network_fee_bps INTEGER NOT NULL CHECK(network_fee_bps >= 0),
                prompt_micro_per_token INTEGER NOT NULL CHECK(prompt_micro_per_token >= 0),
                completion_micro_per_token INTEGER NOT NULL CHECK(completion_micro_per_token >= 0),
                total_charge_micro_units INTEGER NOT NULL CHECK(total_charge_micro_units > 0),
                payload_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING','RECORDED')),
                created_at TEXT NOT NULL,
                recorded_at TEXT
            );
            CREATE INDEX IF NOT EXISTS billing_intent_status_idx
                ON billing_intent(status, created_at);
            """
        )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @staticmethod
    def _normalize_shares(shares: Iterable[tuple[str, float]]) -> tuple[tuple[str, float], ...]:
        value = tuple((str(node), float(ratio)) for node, ratio in shares)
        if not value or any(not node or ratio <= 0 for node, ratio in value):
            raise ValueError("billing intent requires positive provider shares")
        if len({node for node, _ in value}) != len(value):
            raise ValueError("billing intent provider nodes must be unique")
        return value

    @staticmethod
    def _payload_digest(payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def put_pending(
        self,
        *,
        job_id: str,
        account_id: str,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        provider_shares: Iterable[tuple[str, float]],
        network_fee_bps: int,
        prompt_micro_per_token: int,
        completion_micro_per_token: int,
    ) -> BillingIntent:
        job = self.state_store.get_job(job_id)
        if job.state != JobState.COMPLETED:
            raise RuntimeError("billing intent requires a verified COMPLETED job")
        shares = self._normalize_shares(provider_shares)
        total = prompt_tokens * prompt_micro_per_token + completion_tokens * completion_micro_per_token
        total = max(1, total)
        payload = {
            "job_id": job_id,
            "account_id": account_id,
            "model_id": model_id,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "provider_shares": shares,
            "network_fee_bps": int(network_fee_bps),
            "prompt_micro_per_token": int(prompt_micro_per_token),
            "completion_micro_per_token": int(completion_micro_per_token),
            "total_charge_micro_units": total,
        }
        digest = self._payload_digest(payload)
        now = _utc_text(datetime.now(timezone.utc))
        shares_json = json.dumps(shares, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            existing = self._db.execute(
                "SELECT payload_sha256 FROM billing_intent WHERE job_id=?", (job_id,)
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != digest:
                    raise BillingIntentConflict("job already has a different durable billing intent")
                return self.get(job_id)
            self._db.execute(
                "INSERT INTO billing_intent(job_id,account_id,model_id,prompt_tokens,completion_tokens,"
                "provider_shares_json,network_fee_bps,prompt_micro_per_token,completion_micro_per_token,"
                "total_charge_micro_units,payload_sha256,status,created_at,recorded_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'PENDING',?,NULL)",
                (
                    job_id, account_id, model_id, prompt_tokens, completion_tokens, shares_json,
                    network_fee_bps, prompt_micro_per_token, completion_micro_per_token,
                    total, digest, now,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> BillingIntent:
        with self._lock:
            row = self._db.execute("SELECT * FROM billing_intent WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._from_row(row)

    def pending(self) -> tuple[BillingIntent, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM billing_intent WHERE status='PENDING' ORDER BY created_at, job_id"
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def mark_recorded(self, job_id: str) -> bool:
        now = _utc_text(datetime.now(timezone.utc))
        with self._lock:
            cursor = self._db.execute(
                "UPDATE billing_intent SET status='RECORDED', recorded_at=? "
                "WHERE job_id=? AND status='PENDING'",
                (now, job_id),
            )
            if cursor.rowcount == 0:
                row = self._db.execute("SELECT status FROM billing_intent WHERE job_id=?", (job_id,)).fetchone()
                if row is None:
                    raise KeyError(job_id)
                return False
        return True

    @staticmethod
    def _from_row(row: sqlite3.Row) -> BillingIntent:
        shares = tuple((str(node), float(ratio)) for node, ratio in json.loads(row["provider_shares_json"]))
        created = _parse_utc(row["created_at"])
        assert created is not None
        return BillingIntent(
            job_id=row["job_id"], account_id=row["account_id"], model_id=row["model_id"],
            prompt_tokens=row["prompt_tokens"], completion_tokens=row["completion_tokens"],
            provider_shares=shares, network_fee_bps=row["network_fee_bps"],
            prompt_micro_per_token=row["prompt_micro_per_token"],
            completion_micro_per_token=row["completion_micro_per_token"],
            total_charge_micro_units=row["total_charge_micro_units"], status=row["status"],
            created_at=created, recorded_at=_parse_utc(row["recorded_at"]),
        )


def record_intent_exact(ledger, intent: BillingIntent) -> Transaction:
    """Apply a frozen intent without consulting mutable pricing configuration."""
    event_id = f"job:{intent.job_id}"
    lock = getattr(ledger, "_journal_lock", None)
    context = lock if lock is not None else _NullLock()
    with context:
        if event_id in ledger._processed_events:
            raise DuplicateEventError(f"job {intent.job_id} already billed")
        if ledger.get_balance(intent.account_id) < intent.total_charge_micro_units:
            raise InsufficientBalanceError("customer balance insufficient for durable billing intent")
        fee = (intent.total_charge_micro_units * intent.network_fee_bps) // 10000
        pool = intent.total_charge_micro_units - fee
        postings = [Posting(
            account_id=intent.account_id,
            account_type=AccountType.CUSTOMER_DEPOSIT.value,
            debit_micro_units=intent.total_charge_micro_units,
        )]
        if fee:
            postings.append(Posting(
                account_id="revenue:network_fee",
                account_type=AccountType.NETWORK_FEE_REVENUE.value,
                credit_micro_units=fee,
            ))
        total_shares = sum(ratio for _, ratio in intent.provider_shares)
        allocated = 0
        for index, (provider_id, ratio) in enumerate(intent.provider_shares):
            share = pool - allocated if index == len(intent.provider_shares) - 1 else int(pool * ratio / total_shares)
            if index != len(intent.provider_shares) - 1:
                allocated += share
            if share > 0:
                postings.append(Posting(
                    account_id=f"provider:{provider_id}",
                    account_type=AccountType.PROVIDER_PAYABLE.value,
                    credit_micro_units=share,
                ))
        tx = Transaction(
            tx_id=f"tx_job_{hashlib.sha256(event_id.encode('utf-8')).hexdigest()[:16]}",
            event_id=event_id,
            created_at=_utc_text(datetime.now(timezone.utc)) or "",
            description=f"Inference execution for {intent.job_id} ({intent.model_id}, {intent.prompt_tokens}+{intent.completion_tokens} tokens)",
            postings=tuple(postings),
        )
        ledger._record_transaction(tx)
        return tx


class _NullLock:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
