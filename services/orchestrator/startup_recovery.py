"""Fail-closed reconciliation of durable orchestration state after process restart."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
from typing import Iterable

from services.orchestrator.persistence import SQLiteStateStore, StateRecord
from services.orchestrator.state_machine import JobState, ReservationState


_RECOVERABLE_JOB_STATES = frozenset({
    JobState.CREATED,
    JobState.VALIDATING,
    JobState.PLANNING,
    JobState.RESERVING,
    JobState.PREPARING,
    JobState.RUNNING,
    JobState.VERIFYING,
})
_RELEASABLE_RESERVATION_STATES = frozenset({
    ReservationState.LEASED,
    ReservationState.COMMITTED,
    ReservationState.ACTIVE,
})


@dataclass(frozen=True)
class StartupRecoveryReport:
    failed_jobs: tuple[str, ...]
    released_reservations: tuple[str, ...]
    expired_reservations: tuple[str, ...]


class RecoveryStateStore(SQLiteStateStore):
    """Cross-thread live state store with serialized access and recovery enumeration.

    The live gateway creates this store before starting ThreadingHTTPServer and then
    uses it from request threads. Python sqlite connections default to thread-affine;
    this variant explicitly allows cross-thread use and protects each logical store
    operation with one re-entrant lock so transactions cannot interleave.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            super().close()

    def _ensure(self, kind, entity_id, initial_state):
        with self._lock:
            return super()._ensure(kind, entity_id, initial_state)

    def get(self, kind, entity_id):
        with self._lock:
            return super().get(kind, entity_id)

    def get_reservation_binding(self, reservation_id):
        with self._lock:
            return super().get_reservation_binding(reservation_id)

    def _transition(
        self,
        kind,
        entity_id,
        request_id,
        expected_revision,
        target,
        lease_expires_at,
        request_fingerprint,
        binding,
    ):
        with self._lock:
            return super()._transition(
                kind,
                entity_id,
                request_id,
                expected_revision,
                target,
                lease_expires_at,
                request_fingerprint,
                binding,
            )

    def expire_reservation_if_due(
        self,
        reservation_id,
        *,
        request_id,
        expected_revision,
        now,
    ):
        with self._lock:
            return super().expire_reservation_if_due(
                reservation_id,
                request_id=request_id,
                expected_revision=expected_revision,
                now=now,
            )

    def records(self, *, kind: str, states: Iterable[str] | None = None) -> tuple[StateRecord, ...]:
        if kind not in {"job", "reservation"}:
            raise ValueError("kind must be job or reservation")
        state_values = tuple(states or ())
        sql = "SELECT kind, entity_id, state, revision, lease_expires_at FROM entity_state WHERE kind=?"
        params: list[object] = [kind]
        if state_values:
            sql += " AND state IN (" + ",".join("?" for _ in state_values) + ")"
            params.extend(state_values)
        sql += " ORDER BY entity_id"
        with self._lock:
            rows = self._db.execute(sql, tuple(params)).fetchall()
        result: list[StateRecord] = []
        for row in rows:
            state = JobState(row["state"]) if kind == "job" else ReservationState(row["state"])
            lease = None
            if row["lease_expires_at"] is not None:
                lease = datetime.fromisoformat(row["lease_expires_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
            result.append(StateRecord(row["entity_id"], kind, state, row["revision"], lease))
        return tuple(result)

    def reservations_for_job(self, job_id: str) -> tuple[StateRecord, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT e.kind, e.entity_id, e.state, e.revision, e.lease_expires_at "
                "FROM entity_state e JOIN reservation_binding b ON b.reservation_id=e.entity_id "
                "WHERE e.kind='reservation' AND b.job_id=? ORDER BY e.entity_id",
                (job_id,),
            ).fetchall()
        result: list[StateRecord] = []
        for row in rows:
            lease = None
            if row["lease_expires_at"] is not None:
                lease = datetime.fromisoformat(row["lease_expires_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
            result.append(StateRecord(
                row["entity_id"], "reservation", ReservationState(row["state"]), row["revision"], lease
            ))
        return tuple(result)


def reconcile_startup_state(store: RecoveryStateStore, *, now: datetime | None = None) -> StartupRecoveryReport:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    failed_jobs: list[str] = []
    released: list[str] = []
    expired: list[str] = []

    jobs = store.records(kind="job", states=(state.value for state in _RECOVERABLE_JOB_STATES))
    for job in jobs:
        for reservation in store.reservations_for_job(job.entity_id):
            if reservation.state not in _RELEASABLE_RESERVATION_STATES:
                continue
            store.transition_reservation(
                reservation.entity_id,
                request_id=f"startup-recovery-release:{job.entity_id}:{reservation.entity_id}:{reservation.revision}",
                expected_revision=reservation.revision,
                target=ReservationState.RELEASED,
                request_fingerprint="startup_restart_reconciliation_v1",
            )
            released.append(reservation.entity_id)
        latest = store.get_job(job.entity_id)
        if latest.state in _RECOVERABLE_JOB_STATES:
            store.transition_job(
                job.entity_id,
                request_id=f"startup-recovery-fail:{job.entity_id}:{latest.revision}",
                expected_revision=latest.revision,
                target=JobState.FAILED,
                request_fingerprint="startup_restart_reconciliation_v1",
            )
            failed_jobs.append(job.entity_id)

    for reservation in store.records(kind="reservation", states=(ReservationState.LEASED.value,)):
        if reservation.lease_expires_at is None or reservation.lease_expires_at > current:
            continue
        result = store.expire_reservation_if_due(
            reservation.entity_id,
            request_id=f"startup-recovery-expire:{reservation.entity_id}:{reservation.revision}",
            expected_revision=reservation.revision,
            now=current,
        )
        if result is not None:
            expired.append(reservation.entity_id)

    return StartupRecoveryReport(tuple(failed_jobs), tuple(released), tuple(expired))
