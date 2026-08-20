# Job Orchestrator

**Status:** M0 state-machine skeleton implemented; no network service or persistence yet.

## Purpose

Own the canonical job lifecycle and coordinate reservation, dispatch, cancellation, retry/replan, completion, verification, and settlement transitions.

## Current implementation

`state_machine.py` implements an in-memory reference state machine for:

- reservation lifecycle;
- job lifecycle;
- monotonic revisions;
- stale-writer rejection;
- idempotent state-changing requests;
- conflicting idempotency-key detection;
- reservation lease expiry;
- cancellation/failure terminal transitions.

This is a semantic reference implementation for M0. It is deliberately not yet a production service and does not claim durable exactly-once delivery.

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

## Test

```powershell
python -m unittest discover -s services/orchestrator/tests -v
```

The tests cover:

- normal reservation lifecycle;
- duplicate request idempotency;
- conflicting idempotency keys;
- expiry/commit race behavior;
- normal job lifecycle;
- cancellation idempotency;
- stale revisions;
- invalid transitions.

## Next step

Replace the in-memory idempotency/revision store with a transactional persistence adapter, then bind the state machine to the machine-readable job/reservation schemas and protocol handlers.
