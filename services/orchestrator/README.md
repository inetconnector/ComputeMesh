# Job Orchestrator

**Status:** M0 transactional state/persistence and initial durable control handlers implemented; no authenticated network service or production database yet.

## Purpose

Own the canonical job lifecycle and coordinate reservation, dispatch, cancellation, retry/replan, completion, verification, and settlement transitions.

## Current implementation

The M0 reference has four layers:

- `state_machine.py` — deterministic Job/Reservation transition semantics;
- `persistence.py` — transactional SQLite reference storage with durable idempotency, revisions, leases, restart recovery, request fingerprints, and reservation bindings;
- `contracts.py` — JSON Schema Draft 2020-12 validation/admission of initial Job/Reservation documents;
- `handlers.py` — transport-neutral dispatch from validated control envelopes into durable state effects.

### Durable semantics covered

- reservation and job lifecycle;
- monotonic revisions;
- stale-writer rejection across independent database connections;
- durable idempotency across process restart;
- rejection of the same `request_id` when message payload/operation changes;
- reservation lease persistence and expiry;
- cancellation/failure terminal transitions;
- atomic rollback on validation/transition errors;
- initial Job/Reservation schema validation before durable admission;
- SQLite state-store migration v1 → v2;
- atomic `CommitReservation` binding to an existing job and concrete stage.

SQLite is deliberately a **reference persistence adapter**, not the final control-plane database decision. The behavior being stabilized is the contract: atomic mutation, revision checks, durable deduplication, explicit binding, and restart recovery.

## Initial control handlers

Only operations already named in `PROTOCOL.md` are exposed by the initial handler set:

- `ReserveCapacity` — leases an existing reservation until the validated expiry;
- `CommitReservation` — commits the lease and atomically stores job/stage binding;
- `CancelJob` — transitions a cancellable job to `CANCELLED` after validating reason and cutoff policy.

The common envelope `request_id` becomes the durable idempotency key. Message type + payload are fingerprinted, so a replay is harmless but reuse of the same request ID for a changed payload is rejected.

## Reservation lifecycle

```text
CANDIDATE -> LEASED -> COMMITTED -> ACTIVE -> RELEASED
    |           |          |
    v           v          v
 REJECTED     EXPIRED    RELEASED
```

The first network-facing M0 handlers currently implement only the lease and commit portions; the remaining lifecycle messages will be added only when their protocol contracts are defined.

## Job lifecycle

```text
CREATED -> VALIDATING -> PLANNING -> RESERVING -> PREPARING
-> RUNNING -> VERIFYING -> COMPLETED -> SETTLED
```

Alternative terminal outcomes include `CANCELLED`, `FAILED`, and `REFUNDED`. Retries and replans are represented by attempts/placement revisions rather than permanent job states.

## Setup and test

```powershell
python -m pip install -r services/orchestrator/requirements.txt
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
```

The latest isolated regression work verified:

- existing state/persistence/admission behavior plus the new handler/migration cases: 37/37 passing in the assembled regression workspace;
- protocol envelope/payload/schema tests: 15/15 passing;
- relevant Python modules pass `py_compile`.

## Security and reliability boundary

The handler path validates envelope shape/version/expiry, message-specific payloads, revisions, state transitions, and idempotency. It **does not authenticate or authorize `actor_id`**. Signed/authenticated node sessions and service authorization remain required before this can be exposed as a network service.

The handler is also transport-neutral: it does not select gRPC, QUIC, HTTP, or another wire transport.

## Next step

Implement the authenticated node-session skeleton once ADR 0005 is sufficiently specified, then add only the remaining protocol operations required by the selected M1 runtime path. In parallel, collect real two-node and llama.cpp benchmark evidence.
