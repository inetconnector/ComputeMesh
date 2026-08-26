"""Reconcile durable orchestration settlement state with the persistent billing ledger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.orchestrator.startup_recovery import RecoveryStateStore
from services.orchestrator.state_machine import JobState


class LedgerEventView(Protocol):
    _processed_events: set[str]


@dataclass(frozen=True)
class SettlementRecoveryReport:
    settled_jobs: tuple[str, ...]
    pending_jobs: tuple[str, ...]


def acknowledge_job_settlement(store: RecoveryStateStore, job_id: str) -> bool:
    """Move a COMPLETED job to SETTLED after its ledger write succeeds.

    Returns True when the transition was applied and False when the job was already
    SETTLED. Any other state is rejected so billing cannot bless an incomplete job.
    """
    record = store.get_job(job_id)
    if record.state == JobState.SETTLED:
        return False
    if record.state != JobState.COMPLETED:
        raise RuntimeError(f"job {job_id} cannot be settled from {record.state.value}")
    store.transition_job(
        job_id,
        request_id=f"ledger-settlement-ack:{job_id}:{record.revision}",
        expected_revision=record.revision,
        target=JobState.SETTLED,
        request_fingerprint="ledger_job_event_v1",
    )
    return True


def reconcile_completed_settlements(
    store: RecoveryStateStore,
    ledger: LedgerEventView,
) -> SettlementRecoveryReport:
    """Repair the crash window after ledger commit but before orchestration ACK.

    Only an already-persisted ledger event can advance COMPLETED -> SETTLED. A
    COMPLETED job with no matching ledger event is deliberately left pending; this
    function never reconstructs or invents a charge from incomplete state.
    """
    processed = getattr(ledger, "_processed_events", None)
    if not isinstance(processed, set):
        raise RuntimeError("ledger does not expose its loaded processed-event index")
    settled: list[str] = []
    pending: list[str] = []
    for record in store.records(kind="job", states=(JobState.COMPLETED.value,)):
        if f"job:{record.entity_id}" not in processed:
            pending.append(record.entity_id)
            continue
        if acknowledge_job_settlement(store, record.entity_id):
            settled.append(record.entity_id)
    return SettlementRecoveryReport(tuple(settled), tuple(pending))
