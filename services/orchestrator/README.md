# Job Orchestrator

**Status:** durable reference state machine plus authenticated live shared-serving orchestration implemented. The current live path includes authenticated provider control sessions, private global placement, bounded retry/re-placement, verified execution evidence/attestations, durable billing intent/outcome feedback and startup recovery. SQLite remains the current reference/operational persistence adapter rather than a final HA database decision.

## Purpose

Own the canonical job lifecycle and coordinate reservation, dispatch, cancellation, retry/replan, completion, verification, and settlement transitions.

## Current implementation

The original M0 reference remains intact and continues to define the durable semantics:

- `state_machine.py` — deterministic Job/Reservation transition semantics;
- `persistence.py` — transactional SQLite reference storage with durable idempotency, revisions, leases, restart recovery, request fingerprints, and reservation bindings;
- `contracts.py` — JSON Schema Draft 2020-12 validation/admission of initial Job/Reservation documents;
- `handlers.py` — transport-neutral dispatch from validated control envelopes into durable state effects.

The later live-serving layer builds on those contracts rather than replacing them. It includes the live provider control plane, runtime/model registration, authenticated attestation collection, private placement-provider boundary, shared inference backend, cancellation/session-loss handling, durable billing outbox and private measured-outcome feedback.

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
- atomic `CommitReservation` binding to an existing job and concrete stage;
- startup recovery of orphaned in-flight work;
- bounded live retry/re-placement after provider/session loss;
- immutable billing intent persistence before ledger recording;
- idempotent measured-outcome delivery to the private control-plane feedback loop.

SQLite is deliberately a **reference/operational persistence adapter**, not the final production HA database decision. The behavior being stabilized is the contract: atomic mutation, revision checks, durable deduplication, explicit binding, restart recovery and fail-closed settlement/feedback behavior.

## Initial control handlers

The original transport-neutral handler set remains supported:

- `ReserveCapacity` — leases an existing reservation until the validated expiry;
- `CommitReservation` — commits the lease and atomically stores job/stage binding;
- `CancelJob` — transitions a cancellable job to `CANCELLED` after validating reason and cutoff policy.

The common envelope `request_id` becomes the durable idempotency key. Message type + payload are fingerprinted, so a replay is harmless but reuse of the same request ID for a changed payload is rejected.

The live serving path additionally uses the authenticated provider/session components and does not expose these transport-neutral handlers as an unauthenticated public service.

## Reservation lifecycle

```text
CANDIDATE -> LEASED -> COMMITTED -> ACTIVE -> RELEASED
    |           |          |
    v           v          v
 REJECTED     EXPIRED    RELEASED
```

The original handler layer implements the protocol operations already defined for that reference path. The live serving layer adds its own bounded orchestration/recovery behavior while preserving the same fail-closed lifecycle invariants.

## Job lifecycle

```text
CREATED -> VALIDATING -> PLANNING -> RESERVING -> PREPARING
-> RUNNING -> VERIFYING -> COMPLETED -> SETTLED
```

Alternative terminal outcomes include `CANCELLED`, `FAILED`, and `REFUNDED`. Retries and replans are represented by attempts/placement revisions rather than permanent job states.

## Production-placement boundary

The disclosed `services/scheduler/placement.py` planner remains the deterministic M1 research/reference planner. Production live serving defaults to `RemotePlacementProvider`, which submits the complete bounded live candidate/network snapshot to the private ComputeMesh control plane and accepts only a signed, unexpired Ed25519 execution plan.

The public orchestrator therefore executes and defensively validates production placement; it does not contain the production ranking, reputation, fraud, pricing or performance-calibration policy.

## Measured feedback boundary

For remote production placement, successful execution measurements are not considered private performance evidence until public execution evidence and provider attestations verify. The orchestrator durably enqueues a bounded outcome before final completion and retries delivery idempotently to the private control plane. Ordinary execution failures are reported separately from invalid evidence so runtime failure does not automatically become fraud evidence.

Current non-streaming shared inference records measured prefill/decode timing/rates and total request duration. It does not claim true time-to-first-token until upstream token streaming measures that quantity directly.

## Setup and test

```powershell
python -m pip install -r services/orchestrator/requirements.txt
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
```

The repository-wide CI/setup test path is the authoritative current regression check because it also exercises gateway, live runtime, session, billing and feedback integrations. Historical isolated test counts in older documentation should not be treated as the current total suite count.

## Security and reliability boundary

The transport-neutral handler path validates envelope shape/version/expiry, message-specific payloads, revisions, state transitions and idempotency; by itself it does **not** authenticate arbitrary caller-supplied `actor_id` values and must not be exposed as an unauthenticated service.

The live serving path is different: providers use authenticated Ed25519-backed node sessions over the persistent control channel, execution attestations are verified against active identities, and private production placement is signature-verified. Upstream llama.cpp RPC is still an experimental trusted-network implementation detail and is not itself the ComputeMesh security boundary.

## Remaining product-readiness work

The orchestration architecture is no longer waiting for an authenticated node-session skeleton. The remaining gates are empirical and operational:

1. repeat the complete live path on heterogeneous physical nodes under the current private-placement/feedback architecture;
2. run controlled RTT/bandwidth/jitter/disconnect and packet-level network experiments and persist measured evidence;
3. run at least one real two-site WAN validation;
4. replace post-hoc response splitting with true upstream token/chunk streaming and define cancellation/backpressure semantics;
5. calibrate and regression-test production placement against the resulting measured hardware/network envelopes;
6. finish production transport/key-rotation/revocation, disaster-recovery and HA operational procedures.

Until those gates pass, the live path is a signed, fail-closed experimental shared-inference serving system rather than a production-validated untrusted-WAN compute fabric.
