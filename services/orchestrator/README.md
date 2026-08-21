# Job Orchestrator

**Status:** M0 transactional state/persistence reference implemented; no network service or production database yet.

## Purpose

Own the canonical job lifecycle and coordinate reservation, dispatch, cancellation, retry/replan, completion, verification, and settlement transitions.

## Current implementation

The M0 reference now has three layers:

- `state_machine.py` — deterministic job/reservation transition semantics;
- `persistence.py` — transactional SQLite reference storage with durable idempotency and optimistic revisions;
- `contracts.py` — JSON Schema Draft 2020-12 validation and admission of initial Job/Reservation documents.

### Durable semantics already covered

- reservation and job lifecycle;
- monotonic revisions;
- stale-writer rejection across independent database connections;
- durable idempotency across process restart;
- conflicting idempotency-key detection;
- reservation lease persistence and expiry;
- cancellation/failure terminal transitions;
- atomic rollback when validation/transition fails;
- initial Job/Reservation schema validation before durable admission.

SQLite is deliberately a **reference persistence adapter**, not the final control-plane database decision. The production architecture still targets a transactional durable database such as PostgreSQL. The behavior being stabilized here is the contract: atomic state mutation, revision checks, durable deduplication, and restart recovery.

## Reservation lifecycle

```text
CANDIDATE -> LEASED -> COMMITTED -> ACTIVE -> RELEASED
    |           |          |
    v           v          v
 REJECTED     EXPIRED    RELEASED

LEASED may also be explicitly RELEASED before commit.
```

## Job lifecycle

```text
CREATED -> VALIDATING -> PLANNING -> RESERVING -> PREPARING
-> RUNNING -> VERIFYING -> COMPLETED -> SETTLED
```

Alternative terminal outcomes:

- `CANCELLED` before completion;
- `FAILED` before completion;
- `REFUNDED` from `COMPLETED` or `SETTLED`.

Retries and replans are not represented as job states. They become new attempts and placement revisions in the durable model.

## Setup and test

The state machine and SQLite adapter use the Python standard library. Contract validation uses `jsonschema`:

```powershell
python -m pip install -r services/orchestrator/requirements.txt
python -m unittest discover -s services/orchestrator/tests -v
```

Current local verification before publication:

- 8 state-machine tests;
- 8 persistence/restart/concurrency tests;
- 5 contract/admission tests;
- **21/21 total passing**;
- all orchestrator Python modules pass `py_compile`.

## Security/reliability boundary

The admission layer rejects unknown schema fields and invalid privacy/state values before durable creation. This is not yet authentication or authorization: protocol identity, signed node sessions, and service-level authorization remain future work.

## Next step

Bind these semantics to concrete protocol handlers and implement the authenticated node-session skeleton after the node-identity ADR is sufficiently specified. In parallel, run the inventory harness on two real lab machines and start the runtime/transport measurements required by M1.
