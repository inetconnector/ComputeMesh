"""Durable single-use binding between orchestrator jobs and verified execution evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .persistence import SQLiteStateStore


class ExecutionEvidenceBindingError(RuntimeError):
    """Raised when verified evidence cannot be durably bound to a job."""


@dataclass(frozen=True)
class ExecutionEvidenceBinding:
    job_id: str
    evidence_id: str
    document_sha256: str
    placement_decision_id: str
    output_sha256: str
    provider_shares: tuple[tuple[str, float], ...]
    created_at: datetime


class ExecutionEvidenceStore:
    """Small extension table sharing the orchestrator SQLite database.

    Evidence document digests and evidence IDs are globally unique, preventing one
    proof from being replayed to settle multiple jobs.
    """

    def __init__(self, state_store: SQLiteStateStore):
        self.state_store = state_store
        self.path = state_store.path
        self._db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS execution_evidence_binding (
                job_id TEXT PRIMARY KEY,
                evidence_id TEXT NOT NULL UNIQUE,
                document_sha256 TEXT NOT NULL UNIQUE,
                placement_decision_id TEXT NOT NULL,
                output_sha256 TEXT NOT NULL,
                provider_shares_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self._db.close()

    @staticmethod
    def _normalize_shares(
        provider_shares: Iterable[tuple[str, float]],
    ) -> tuple[tuple[str, float], ...]:
        normalized = tuple((str(node_id), float(ratio)) for node_id, ratio in provider_shares)
        if len(normalized) < 2:
            raise ValueError("verified shared execution requires at least two provider shares")
        if len({node_id for node_id, _ in normalized}) != len(normalized):
            raise ValueError("provider share node ids must be unique")
        if any(not node_id or ratio <= 0 for node_id, ratio in normalized):
            raise ValueError("provider shares require non-empty nodes and positive ratios")
        return normalized

    def bind(
        self,
        *,
        job_id: str,
        evidence_id: str,
        document_sha256: str,
        placement_decision_id: str,
        output_sha256: str,
        provider_shares: Iterable[tuple[str, float]],
    ) -> ExecutionEvidenceBinding:
        if not all((job_id, evidence_id, document_sha256, placement_decision_id, output_sha256)):
            raise ValueError("execution evidence binding fields must not be empty")
        # Fail before touching the extension table when the orchestration job does not exist.
        self.state_store.get_job(job_id)
        shares = self._normalize_shares(provider_shares)
        payload = json.dumps(shares, separators=(",", ":"), ensure_ascii=False)
        created_at = datetime.now(timezone.utc)
        created_text = created_at.isoformat().replace("+00:00", "Z")
        try:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute(
                "INSERT INTO execution_evidence_binding("
                "job_id, evidence_id, document_sha256, placement_decision_id, "
                "output_sha256, provider_shares_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    evidence_id,
                    document_sha256,
                    placement_decision_id,
                    output_sha256,
                    payload,
                    created_text,
                ),
            )
            self._db.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            self._db.execute("ROLLBACK")
            raise ExecutionEvidenceBindingError(
                "execution evidence is already bound to this or another job"
            ) from exc
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return ExecutionEvidenceBinding(
            job_id,
            evidence_id,
            document_sha256,
            placement_decision_id,
            output_sha256,
            shares,
            created_at,
        )

    def get(self, job_id: str) -> ExecutionEvidenceBinding:
        row = self._db.execute(
            "SELECT job_id, evidence_id, document_sha256, placement_decision_id, "
            "output_sha256, provider_shares_json, created_at "
            "FROM execution_evidence_binding WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no execution evidence binding for job {job_id!r}")
        raw_shares = json.loads(row["provider_shares_json"])
        shares = tuple((str(node_id), float(ratio)) for node_id, ratio in raw_shares)
        created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        return ExecutionEvidenceBinding(
            row["job_id"],
            row["evidence_id"],
            row["document_sha256"],
            row["placement_decision_id"],
            row["output_sha256"],
            shares,
            created_at,
        )
