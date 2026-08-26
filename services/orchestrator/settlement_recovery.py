"""Reconcile durable orchestration settlement state with the persistent billing ledger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from services.orchestrator.billing_intent import BillingIntentStore, record_intent_exact
from services.orchestrator.startup_recovery import RecoveryStateStore
from services.orchestrator.state_machine import JobState


class LedgerEventView(Protocol):
    _processed_events: set[str]


@dataclass(frozen=True)
class SettlementRecoveryReport:
    settled_jobs: tuple[str, ...]
    pending_jobs: tuple[str, ...]


@dataclass(frozen=True)
class BillingOutboxReplayReport:
    replayed_jobs: tuple[str, ...]
    repaired_recorded_jobs: tuple[str, ...]
    settled_jobs: tuple[str, ...]


def acknowledge_job_settlement(store: RecoveryStateStore, job_id: str) -> bool:
    """Move a COMPLETED job to SETTLED after its ledger write succeeds."""
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


def replay_billing_outbox(
    store: RecoveryStateStore,
    ledger: LedgerEventView,
) -> BillingOutboxReplayReport:
    """Replay PENDING billing intents before accepting new live traffic.

    The frozen intent contains the exact account, provider split, fee bps and unit
    prices observed after verified execution. If the ledger event already exists,
    only the missing outbox/settlement acknowledgement is repaired. Otherwise the
    exact frozen transaction is appended once and then acknowledged.
    """
    processed = getattr(ledger, "_processed_events", None)
    if not isinstance(processed, set):
        raise RuntimeError("ledger does not expose its loaded processed-event index")

    intents = BillingIntentStore(store)
    replayed: list[str] = []
    repaired: list[str] = []
    settled: list[str] = []
    try:
        for intent in intents.pending():
            event_id = f"job:{intent.job_id}"
            if event_id in processed:
                intents.mark_recorded(intent.job_id)
                repaired.append(intent.job_id)
            else:
                record_intent_exact(ledger, intent)
                intents.mark_recorded(intent.job_id)
                replayed.append(intent.job_id)

            state = store.get_job(intent.job_id).state
            if state == JobState.COMPLETED and acknowledge_job_settlement(store, intent.job_id):
                settled.append(intent.job_id)
            elif state != JobState.SETTLED:
                raise RuntimeError(
                    f"recorded billing intent {intent.job_id} has incompatible job state {state.value}"
                )
    finally:
        intents.close()
    return BillingOutboxReplayReport(tuple(replayed), tuple(repaired), tuple(settled))


def reconcile_completed_settlements(
    store: RecoveryStateStore,
    ledger: LedgerEventView,
) -> SettlementRecoveryReport:
    """Repair legacy crash windows after ledger commit but before orchestration ACK.

    New live jobs use the billing outbox. This pass remains as a compatibility
    repair for durable COMPLETED records created before the outbox existed.
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
