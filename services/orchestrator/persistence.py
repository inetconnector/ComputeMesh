from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Literal

try:
    from .state_machine import (
        IdempotencyConflict,
        InvalidTransition,
        JobState,
        ReservationState,
        StaleRevision,
        TransitionResult,
        _JOB_CANCELLABLE,
        _JOB_FAILABLE,
        _JOB_FORWARD,
        _RESERVATION_TRANSITIONS,
    )
except ImportError:  # direct-file execution/tests
    from state_machine import (
        IdempotencyConflict,
        InvalidTransition,
        JobState,
        ReservationState,
        StaleRevision,
        TransitionResult,
        _JOB_CANCELLABLE,
        _JOB_FAILABLE,
        _JOB_FORWARD,
        _RESERVATION_TRANSITIONS,
    )

EntityKind = Literal["job", "reservation"]


@dataclass(frozen=True)
class StateRecord:
    entity_id: str
    kind: EntityKind
    state: JobState | ReservationState
    revision: int
    lease_expires_at: datetime | None


@dataclass(frozen=True)
class ReservationBinding:
    reservation_id: str
    job_id: str
    stage_id: str
    request_id: str
    created_at: datetime


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class SQLiteStateStore:
    """Transactional M0 persistence for job and reservation state.

    SQLite remains a reference persistence layer rather than the final
    control-plane database choice. The important contract is transactional
    state, durable idempotency, optimistic revision checks, and atomic
    reservation-to-job/stage binding.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SQLiteStateStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _migrate(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');

            CREATE TABLE IF NOT EXISTS entity_state (
                kind TEXT NOT NULL CHECK(kind IN ('job', 'reservation')),
                entity_id TEXT NOT NULL,
                state TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 0),
                lease_expires_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(kind, entity_id)
            );

            CREATE TABLE IF NOT EXISTS idempotency_effect (
                kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                target_state TEXT NOT NULL,
                result_state TEXT NOT NULL,
                result_revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(kind, entity_id, request_id),
                FOREIGN KEY(kind, entity_id) REFERENCES entity_state(kind, entity_id)
                    ON DELETE CASCADE
            );
            """
        )

        version = self._db.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]

        if version == "1":
            columns = {
                row["name"]
                for row in self._db.execute("PRAGMA table_info(idempotency_effect)").fetchall()
            }
            if "request_fingerprint" not in columns:
                self._db.execute(
                    "ALTER TABLE idempotency_effect "
                    "ADD COLUMN request_fingerprint TEXT NOT NULL DEFAULT ''"
                )

            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS reservation_binding (
                    reservation_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    stage_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._db.execute(
                "UPDATE schema_meta SET value='2' WHERE key='schema_version'"
            )
            version = "2"

        if version != "2":
            raise RuntimeError(f"unsupported state-store schema version {version}")

    def ensure_job(self, job_id: str) -> StateRecord:
        return self._ensure("job", job_id, JobState.CREATED.value)

    def ensure_reservation(self, reservation_id: str) -> StateRecord:
        return self._ensure("reservation", reservation_id, ReservationState.CANDIDATE.value)

    def _ensure(self, kind: EntityKind, entity_id: str, initial_state: str) -> StateRecord:
        if not entity_id:
            raise ValueError("entity_id is required")
        now = _utc_text(datetime.now(timezone.utc))
        self._db.execute(
            "INSERT OR IGNORE INTO entity_state("
            "kind, entity_id, state, revision, lease_expires_at, updated_at"
            ") VALUES (?, ?, ?, 0, NULL, ?)",
            (kind, entity_id, initial_state, now),
        )
        return self.get(kind, entity_id)

    def get_job(self, job_id: str) -> StateRecord:
        return self.get("job", job_id)

    def get_reservation(self, reservation_id: str) -> StateRecord:
        return self.get("reservation", reservation_id)

    def get(self, kind: EntityKind, entity_id: str) -> StateRecord:
        row = self._db.execute(
            "SELECT kind, entity_id, state, revision, lease_expires_at "
            "FROM entity_state WHERE kind=? AND entity_id=?",
            (kind, entity_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown {kind} {entity_id!r}")
        state = JobState(row["state"]) if kind == "job" else ReservationState(row["state"])
        return StateRecord(
            row["entity_id"],
            kind,
            state,
            row["revision"],
            _parse_utc(row["lease_expires_at"]),
        )

    def get_reservation_binding(self, reservation_id: str) -> ReservationBinding:
        row = self._db.execute(
            "SELECT reservation_id, job_id, stage_id, request_id, created_at "
            "FROM reservation_binding WHERE reservation_id=?",
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no binding for reservation {reservation_id!r}")
        created_at = _parse_utc(row["created_at"])
        assert created_at is not None
        return ReservationBinding(
            row["reservation_id"],
            row["job_id"],
            row["stage_id"],
            row["request_id"],
            created_at,
        )

    def transition_job(
        self,
        job_id: str,
        *,
        request_id: str,
        expected_revision: int,
        target: JobState,
        request_fingerprint: str = "",
    ) -> TransitionResult[JobState]:
        return self._transition(
            "job",
            job_id,
            request_id,
            expected_revision,
            target,
            None,
            request_fingerprint,
            None,
        )

    def lease_reservation(
        self,
        reservation_id: str,
        *,
        request_id: str,
        expected_revision: int,
        expires_at: datetime,
        request_fingerprint: str = "",
    ) -> TransitionResult[ReservationState]:
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if expires_at <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return self._transition(
            "reservation",
            reservation_id,
            request_id,
            expected_revision,
            ReservationState.LEASED,
            expires_at,
            request_fingerprint,
            None,
        )

    def commit_reservation(
        self,
        reservation_id: str,
        *,
        request_id: str,
        expected_revision: int,
        job_id: str,
        stage_id: str,
        request_fingerprint: str = "",
    ) -> TransitionResult[ReservationState]:
        if not job_id or not stage_id:
            raise ValueError("job_id and stage_id are required")
        return self._transition(
            "reservation",
            reservation_id,
            request_id,
            expected_revision,
            ReservationState.COMMITTED,
            None,
            request_fingerprint,
            (job_id, stage_id),
        )

    def transition_reservation(
        self,
        reservation_id: str,
        *,
        request_id: str,
        expected_revision: int,
        target: ReservationState,
        request_fingerprint: str = "",
    ) -> TransitionResult[ReservationState]:
        return self._transition(
            "reservation",
            reservation_id,
            request_id,
            expected_revision,
            target,
            None,
            request_fingerprint,
            None,
        )

    def expire_reservation_if_due(
        self,
        reservation_id: str,
        *,
        request_id: str,
        expected_revision: int,
        now: datetime,
    ) -> TransitionResult[ReservationState] | None:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        record = self.get_reservation(reservation_id)
        if record.state != ReservationState.LEASED or record.lease_expires_at is None:
            return None
        if now.astimezone(timezone.utc) < record.lease_expires_at:
            return None
        return self.transition_reservation(
            reservation_id,
            request_id=request_id,
            expected_revision=expected_revision,
            target=ReservationState.EXPIRED,
        )

    def _allowed(
        self,
        kind: EntityKind,
        state: JobState | ReservationState,
    ) -> set[JobState] | set[ReservationState]:
        if kind == "reservation":
            return _RESERVATION_TRANSITIONS[ReservationState(state)]
        job_state = JobState(state)
        allowed = set(_JOB_FORWARD[job_state])
        if job_state in _JOB_CANCELLABLE:
            allowed.add(JobState.CANCELLED)
        if job_state in _JOB_FAILABLE:
            allowed.add(JobState.FAILED)
        return allowed

    def _transition(
        self,
        kind: EntityKind,
        entity_id: str,
        request_id: str,
        expected_revision: int,
        target: JobState | ReservationState,
        lease_expires_at: datetime | None,
        request_fingerprint: str,
        binding: tuple[str, str] | None,
    ):
        if not request_id:
            raise ValueError("request_id is required")

        target_value = target.value
        self._db.execute("BEGIN IMMEDIATE")
        try:
            prior = self._db.execute(
                "SELECT target_state, result_state, result_revision, request_fingerprint "
                "FROM idempotency_effect "
                "WHERE kind=? AND entity_id=? AND request_id=?",
                (kind, entity_id, request_id),
            ).fetchone()
            if prior is not None:
                if (
                    prior["target_state"] != target_value
                    or prior["request_fingerprint"] != request_fingerprint
                ):
                    raise IdempotencyConflict(
                        f"request_id {request_id!r} was already used for a different "
                        "operation or payload"
                    )
                result_state = (
                    JobState(prior["result_state"])
                    if kind == "job"
                    else ReservationState(prior["result_state"])
                )
                self._db.execute("COMMIT")
                return TransitionResult(
                    result_state,
                    prior["result_revision"],
                    request_id,
                    False,
                )

            row = self._db.execute(
                "SELECT state, revision, lease_expires_at "
                "FROM entity_state WHERE kind=? AND entity_id=?",
                (kind, entity_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown {kind} {entity_id!r}")
            if row["revision"] != expected_revision:
                raise StaleRevision(
                    f"expected revision {expected_revision}, current revision {row['revision']}"
                )

            current = JobState(row["state"]) if kind == "job" else ReservationState(row["state"])
            if target not in self._allowed(kind, current):
                raise InvalidTransition(
                    f"cannot transition from {current.value} to {target_value}"
                )

            if binding is not None:
                job_id, _stage_id = binding
                job_row = self._db.execute(
                    "SELECT state FROM entity_state WHERE kind='job' AND entity_id=?",
                    (job_id,),
                ).fetchone()
                if job_row is None:
                    raise KeyError(f"unknown job {job_id!r}")

            next_revision = expected_revision + 1
            if kind == "reservation":
                if target == ReservationState.LEASED:
                    lease_text = _utc_text(lease_expires_at)
                elif target in {
                    ReservationState.RELEASED,
                    ReservationState.EXPIRED,
                    ReservationState.REJECTED,
                }:
                    lease_text = None
                else:
                    lease_text = row["lease_expires_at"]
            else:
                lease_text = None

            now_text = _utc_text(datetime.now(timezone.utc))
            cursor = self._db.execute(
                "UPDATE entity_state "
                "SET state=?, revision=?, lease_expires_at=?, updated_at=? "
                "WHERE kind=? AND entity_id=? AND revision=?",
                (
                    target_value,
                    next_revision,
                    lease_text,
                    now_text,
                    kind,
                    entity_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleRevision("state changed concurrently")

            if binding is not None:
                job_id, stage_id = binding
                self._db.execute(
                    "INSERT INTO reservation_binding("
                    "reservation_id, job_id, stage_id, request_id, created_at"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (entity_id, job_id, stage_id, request_id, now_text),
                )

            self._db.execute(
                "INSERT INTO idempotency_effect("
                "kind, entity_id, request_id, target_state, result_state, "
                "result_revision, created_at, request_fingerprint"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    kind,
                    entity_id,
                    request_id,
                    target_value,
                    target_value,
                    next_revision,
                    now_text,
                    request_fingerprint,
                ),
            )
            self._db.execute("COMMIT")
            return TransitionResult(target, next_revision, request_id, True)
        except Exception:
            self._db.execute("ROLLBACK")
            raise
