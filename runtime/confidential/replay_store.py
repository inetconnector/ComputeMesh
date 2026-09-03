"""Durable single-use replay protection for confidential request envelopes.

A protected envelope is consumed before dispatch.  Once claimed, the same
envelope_id can never execute again through this store, even if downstream
execution fails.  Clients retry by creating a fresh envelope bound to fresh
attestation state rather than replaying protected ciphertext.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Protocol

from protocol.confidential_envelope import ConfidentialEnvelope


class ConfidentialReplayError(RuntimeError):
    pass


class ConfidentialReplayDetected(ConfidentialReplayError):
    pass


class ConfidentialReplayBindingError(ConfidentialReplayError):
    pass


@dataclass(frozen=True)
class ReplayClaim:
    envelope_id: str
    account_id: str
    job_id: str
    node_id: str
    privacy_class: str
    operation: str
    binding_digest: str
    claimed_at: str


class ConfidentialReplayStore(Protocol):
    def claim(
        self,
        envelope: ConfidentialEnvelope,
        *,
        expected_account_id: str,
        expected_privacy_class: str,
        expected_operation: str,
        now: datetime | None = None,
    ) -> ReplayClaim:
        """Atomically consume an envelope or fail if it was already seen."""


class SQLiteConfidentialReplayStore:
    """SQLite-backed replay tombstones safe across gateway processes/restarts."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(self.path) == ":memory:":
            raise ValueError("confidential replay state must be durable; :memory: is not allowed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS confidential_replay_claims (
                    envelope_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    privacy_class TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    binding_digest TEXT NOT NULL,
                    claimed_at TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )

    @staticmethod
    def _binding_digest(envelope: ConfidentialEnvelope) -> str:
        document = {
            "schema_version": envelope.schema_version,
            "algorithm": envelope.algorithm,
            "envelope_id": envelope.envelope_id,
            "binding": envelope.binding.as_dict(),
            "sender_ephemeral_public_key": envelope.sender_ephemeral_public_key,
            "salt": envelope.salt,
            "nonce": envelope.nonce,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def claim(
        self,
        envelope: ConfidentialEnvelope,
        *,
        expected_account_id: str,
        expected_privacy_class: str,
        expected_operation: str,
        now: datetime | None = None,
    ) -> ReplayClaim:
        envelope.validate()
        binding = envelope.binding
        if binding.account_id != expected_account_id:
            raise ConfidentialReplayBindingError("confidential envelope account binding mismatch")
        if binding.privacy_class != expected_privacy_class:
            raise ConfidentialReplayBindingError("confidential envelope privacy binding mismatch")
        if binding.operation != expected_operation:
            raise ConfidentialReplayBindingError("confidential envelope operation binding mismatch")

        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("replay claim timestamp must be timezone-aware")
        claimed_at = instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        digest = self._binding_digest(envelope)
        claim = ReplayClaim(
            envelope_id=envelope.envelope_id,
            account_id=binding.account_id,
            job_id=binding.job_id,
            node_id=binding.node_id,
            privacy_class=binding.privacy_class,
            operation=binding.operation,
            binding_digest=digest,
            claimed_at=claimed_at,
        )

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO confidential_replay_claims (
                        envelope_id, account_id, job_id, node_id,
                        privacy_class, operation, binding_digest, claimed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim.envelope_id,
                        claim.account_id,
                        claim.job_id,
                        claim.node_id,
                        claim.privacy_class,
                        claim.operation,
                        claim.binding_digest,
                        claim.claimed_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                raise ConfidentialReplayDetected("confidential envelope was already consumed") from exc
            connection.execute("COMMIT")
            return claim

    def get_claim(self, envelope_id: str) -> ReplayClaim | None:
        if not isinstance(envelope_id, str) or len(envelope_id) != 32:
            raise ValueError("invalid envelope_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT envelope_id, account_id, job_id, node_id,
                       privacy_class, operation, binding_digest, claimed_at
                FROM confidential_replay_claims
                WHERE envelope_id = ?
                """,
                (envelope_id,),
            ).fetchone()
        if row is None:
            return None
        return ReplayClaim(*row)

    def purge_before(self, cutoff: datetime) -> int:
        """Operator maintenance only; retention must exceed max attestation/retry horizon."""
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("replay purge cutoff must be timezone-aware")
        cutoff_text = cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM confidential_replay_claims WHERE claimed_at < ?",
                (cutoff_text,),
            )
            return max(int(cursor.rowcount), 0)
