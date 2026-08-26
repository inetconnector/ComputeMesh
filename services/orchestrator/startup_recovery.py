"""Fail-closed reconciliation of durable orchestration state after process restart."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    """SQLiteStateStore with bounded enumeration used only for startup recovery."""

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
    """Make durable state safe before accepting new requests after a restart.

    A restarted control-plane process cannot prove that an old in-flight runtime process,
    its authenticated sessions, or its cancellation handle are still the same execution.
    In-flight jobs are therefore failed rather than resumed. Bound capacity is released,
    and expired unbound leases are expired. Terminal/settlement states are untouched.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    failed_jobs: list[str] = []
    released: list[str] = []
    expired: list[str] = []

    jobs = store.records(kind="job", states=(state.value for state in _RECOVERABLE_JOB_STATES))
    for job in jobs:
        # Release capacity first. If the process dies again after this point, the job is
        # still fail-able on the next startup; capacity will not stay stuck ACTIVE.
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

    # Leased candidates without a committed job binding are independently safe to expire
    # once their durable lease deadline has passed.
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
