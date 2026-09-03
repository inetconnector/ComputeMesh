"""Durable, content-free confidential session admission and metering state.

A session is created before any customer prompt is sent. The production broker
selects a suitable confidential runtime and returns only the chosen attested
endpoint/evidence; public gateway code keeps no ranking inputs. After execution,
only a signed content-free usage receipt is persisted before ledger capture.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Protocol

from protocol.confidential_metering import ConfidentialUsageReceipt
from runtime.confidential.data_plane import AttestedConfidentialEndpoint


class ConfidentialSessionError(RuntimeError):
    pass


class ConfidentialSessionStateError(ConfidentialSessionError):
    pass


@dataclass(frozen=True)
class ConfidentialSessionProvision:
    job_id: str
    account_id: str
    model_id: str
    privacy_class: str
    operation: str
    max_prompt_tokens: int
    max_completion_tokens: int
    endpoint: AttestedConfidentialEndpoint
    attestation: Mapping[str, Any]
    expires_at: str

    def validate(self) -> None:
        for name, value, limit in (
            ("job_id", self.job_id, 256),
            ("account_id", self.account_id, 256),
            ("model_id", self.model_id, 512),
            ("privacy_class", self.privacy_class, 64),
            ("operation", self.operation, 64),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ConfidentialSessionError(f"invalid {name}")
        if self.privacy_class not in {"CONFIDENTIAL", "CRYPTO_PRIVATE"}:
            raise ConfidentialSessionError("invalid confidential session privacy class")
        if self.operation not in {"chat_completion", "ollama_chat", "ollama_generate"}:
            raise ConfidentialSessionError("invalid confidential session operation")
        for name, value in (
            ("max_prompt_tokens", self.max_prompt_tokens),
            ("max_completion_tokens", self.max_completion_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value > 1_000_000:
                raise ConfidentialSessionError(f"invalid {name}")
        self.endpoint.validate()
        if self.endpoint.node_id != str(self.attestation.get("node_id", "")):
            raise ConfidentialSessionError("session endpoint node does not match attestation")
        if self.endpoint.runtime_digest != str(self.attestation.get("runtime_digest", "")):
            raise ConfidentialSessionError("session endpoint runtime does not match attestation")
        if self.endpoint.attestation_nonce != str(self.attestation.get("nonce", "")):
            raise ConfidentialSessionError("session endpoint nonce does not match attestation")
        if self.endpoint.recipient_public_key != str(self.attestation.get("ephemeral_public_key", "")):
            raise ConfidentialSessionError("session recipient key does not match attestation")
        if self.endpoint.metering_public_key != str(self.attestation.get("metering_public_key", "")):
            raise ConfidentialSessionError("session metering key does not match attestation")
        if self.endpoint.tls_certificate_sha256 != str(self.attestation.get("data_plane_tls_sha256", "")):
            raise ConfidentialSessionError("session TLS identity does not match attestation")
        _timestamp(self.expires_at)

    def public_descriptor(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": 1,
            "job_id": self.job_id,
            "model_id": self.model_id,
            "privacy_class": self.privacy_class,
            "operation": self.operation,
            "max_prompt_tokens": self.max_prompt_tokens,
            "max_completion_tokens": self.max_completion_tokens,
            "expires_at": self.expires_at,
            "node_id": self.endpoint.node_id,
            "runtime_digest": self.endpoint.runtime_digest,
            "attestation_nonce": self.endpoint.attestation_nonce,
            "recipient_public_key": self.endpoint.recipient_public_key,
            "metering_public_key": self.endpoint.metering_public_key,
            "data_plane_tls_sha256": self.endpoint.tls_certificate_sha256,
            "attestation": dict(self.attestation),
        }


class ConfidentialSessionBroker(Protocol):
    def provision(
        self,
        *,
        account_id: str,
        model_id: str,
        privacy_class: str,
        operation: str,
        max_prompt_tokens: int,
        max_completion_tokens: int,
    ) -> ConfidentialSessionProvision:
        """Select and freshly attest one protected runtime without customer content."""


@dataclass(frozen=True)
class ConfidentialSessionRecord:
    job_id: str
    account_id: str
    model_id: str
    privacy_class: str
    operation: str
    max_prompt_tokens: int
    max_completion_tokens: int
    hold_id: str
    node_id: str
    runtime_digest: str
    attestation_nonce: str
    recipient_public_key: str
    metering_public_key: str
    data_plane_tls_sha256: str
    endpoint_url: str
    attestation_json: str
    expires_at: str
    state: str
    envelope_id: str | None
    usage_receipt_json: str | None
    created_at: str
    updated_at: str

    @property
    def endpoint(self) -> AttestedConfidentialEndpoint:
        return AttestedConfidentialEndpoint(
            url=self.endpoint_url,
            node_id=self.node_id,
            runtime_digest=self.runtime_digest,
            attestation_nonce=self.attestation_nonce,
            recipient_public_key=self.recipient_public_key,
            metering_public_key=self.metering_public_key,
            tls_certificate_sha256=self.data_plane_tls_sha256,
        )

    @property
    def attestation(self) -> Mapping[str, Any]:
        value = json.loads(self.attestation_json)
        if not isinstance(value, dict):
            raise ConfidentialSessionError("stored confidential attestation is invalid")
        return value

    @property
    def usage_receipt(self) -> ConfidentialUsageReceipt | None:
        if self.usage_receipt_json is None:
            return None
        value = json.loads(self.usage_receipt_json)
        if not isinstance(value, dict):
            raise ConfidentialSessionError("stored confidential usage receipt is invalid")
        return ConfidentialUsageReceipt.from_dict(value)


class SQLiteConfidentialSessionStore:
    """Durable lifecycle; never stores prompt/output plaintext or ciphertext."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(self.path) == ":memory:":
            raise ValueError("confidential session state must be durable")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS confidential_sessions (
                    job_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    privacy_class TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    max_prompt_tokens INTEGER NOT NULL,
                    max_completion_tokens INTEGER NOT NULL,
                    hold_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    runtime_digest TEXT NOT NULL,
                    attestation_nonce TEXT NOT NULL,
                    recipient_public_key TEXT NOT NULL,
                    metering_public_key TEXT NOT NULL,
                    data_plane_tls_sha256 TEXT NOT NULL,
                    endpoint_url TEXT NOT NULL,
                    attestation_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    envelope_id TEXT,
                    usage_receipt_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )

    def create(self, provision: ConfidentialSessionProvision, *, hold_id: str) -> ConfidentialSessionRecord:
        provision.validate()
        if not isinstance(hold_id, str) or not hold_id or len(hold_id) > 256:
            raise ConfidentialSessionError("invalid confidential session hold_id")
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        record = ConfidentialSessionRecord(
            job_id=provision.job_id,
            account_id=provision.account_id,
            model_id=provision.model_id,
            privacy_class=provision.privacy_class,
            operation=provision.operation,
            max_prompt_tokens=provision.max_prompt_tokens,
            max_completion_tokens=provision.max_completion_tokens,
            hold_id=hold_id,
            node_id=provision.endpoint.node_id,
            runtime_digest=provision.endpoint.runtime_digest,
            attestation_nonce=provision.endpoint.attestation_nonce,
            recipient_public_key=provision.endpoint.recipient_public_key,
            metering_public_key=provision.endpoint.metering_public_key,
            data_plane_tls_sha256=provision.endpoint.tls_certificate_sha256,
            endpoint_url=provision.endpoint.url,
            attestation_json=json.dumps(provision.attestation, sort_keys=True, separators=(",", ":")),
            expires_at=provision.expires_at,
            state="OPEN",
            envelope_id=None,
            usage_receipt_json=None,
            created_at=now,
            updated_at=now,
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO confidential_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(record.__dict__.values()),
                )
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                raise ConfidentialSessionError("confidential session job_id already exists") from exc
            connection.execute("COMMIT")
        finally:
            connection.close()
        return record

    def get(self, job_id: str) -> ConfidentialSessionRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM confidential_sessions WHERE job_id = ?", (job_id,)).fetchone()
        return ConfidentialSessionRecord(*row) if row else None

    def begin_dispatch(
        self,
        *,
        job_id: str,
        account_id: str,
        envelope_id: str,
        now: datetime | None = None,
    ) -> ConfidentialSessionRecord:
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("confidential session dispatch timestamp must be timezone-aware")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM confidential_sessions WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise ConfidentialSessionStateError("confidential session not found")
            record = ConfidentialSessionRecord(*row)
            if record.account_id != account_id:
                connection.execute("ROLLBACK")
                raise ConfidentialSessionStateError("confidential session account mismatch")
            if record.state != "OPEN":
                connection.execute("ROLLBACK")
                raise ConfidentialSessionStateError("confidential session is not open")
            if _timestamp(record.expires_at) <= current.astimezone(UTC):
                connection.execute(
                    "UPDATE confidential_sessions SET state='EXPIRED', updated_at=? WHERE job_id=?",
                    (current.astimezone(UTC).isoformat().replace("+00:00", "Z"), job_id),
                )
                connection.execute("COMMIT")
                raise ConfidentialSessionStateError("confidential session expired")
            updated_at = current.astimezone(UTC).isoformat().replace("+00:00", "Z")
            connection.execute(
                "UPDATE confidential_sessions SET state='DISPATCHED', envelope_id=?, updated_at=? WHERE job_id=?",
                (envelope_id, updated_at, job_id),
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        updated = self.get(job_id)
        if updated is None:
            raise ConfidentialSessionStateError("confidential session disappeared")
        return updated

    def record_metering(self, *, job_id: str, receipt: ConfidentialUsageReceipt) -> ConfidentialSessionRecord:
        receipt.validate()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM confidential_sessions WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise ConfidentialSessionStateError("confidential session not found")
            record = ConfidentialSessionRecord(*row)
            if record.state != "DISPATCHED" or record.envelope_id is None:
                connection.execute("ROLLBACK")
                raise ConfidentialSessionStateError("confidential session is not awaiting metering")
            if receipt.job_id != record.job_id or receipt.request_envelope_id != record.envelope_id:
                connection.execute("ROLLBACK")
                raise ConfidentialSessionStateError("confidential metering receipt does not match session")
            updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            connection.execute(
                "UPDATE confidential_sessions SET state='METERED', usage_receipt_json=?, updated_at=? WHERE job_id=?",
                (json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")), updated_at, job_id),
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        updated = self.get(job_id)
        if updated is None:
            raise ConfidentialSessionStateError("confidential session disappeared")
        return updated

    def finish(self, *, job_id: str, target: str) -> ConfidentialSessionRecord:
        if target not in {"COMPLETED", "FAILED"}:
            raise ValueError("invalid confidential session terminal state")
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if target == "COMPLETED":
                cursor = connection.execute(
                    "UPDATE confidential_sessions SET state='COMPLETED', updated_at=? WHERE job_id=? AND state='METERED'",
                    (now, job_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE confidential_sessions SET state='FAILED', updated_at=? WHERE job_id=? AND state IN ('DISPATCHED','METERED')",
                    (now, job_id),
                )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise ConfidentialSessionStateError("confidential session cannot enter terminal state")
            connection.execute("COMMIT")
        finally:
            connection.close()
        record = self.get(job_id)
        if record is None:
            raise ConfidentialSessionStateError("confidential session disappeared")
        return record

    def list_metered(self, *, limit: int = 100) -> tuple[ConfidentialSessionRecord, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("invalid confidential metering reconciliation limit")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM confidential_sessions WHERE state='METERED' ORDER BY updated_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(ConfidentialSessionRecord(*row) for row in rows)


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ConfidentialSessionError("invalid confidential session timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConfidentialSessionError("invalid confidential session timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConfidentialSessionError("confidential session timestamp must be timezone-aware")
    return parsed.astimezone(UTC)
