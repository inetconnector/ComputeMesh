# ComputeMesh Test Matrix

**Status:** Draft v0.1

## Test categories

| Component | Unit | Integration | Property/Replay | Performance | Chaos | Security |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gateway | ✓ | ✓ | ✓ | ✓ |  | ✓ |
| Orchestrator | ✓ | ✓ | ✓ |  | ✓ | ✓ |
| Scheduler | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| Registry | ✓ | ✓ | ✓ |  |  | ✓ |
| Node agent | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Runtime | ✓ | ✓ |  | ✓ | ✓ | ✓ |
| Protocol | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Verification | ✓ | ✓ | ✓ | ✓ |  | ✓ |
| Billing/ledger | ✓ | ✓ | ✓ |  | ✓ | ✓ |
| Telemetry | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Update pipeline | ✓ | ✓ |  |  | ✓ | ✓ |

## Mandatory invariants

### Protocol

- duplicate mutation has one effect;
- expired command rejected;
- stale revision rejected;
- malformed/oversized frame rejected;
- unknown critical feature rejected;
- cancellation idempotent.

### Scheduler

- hard constraints never bypassed by score;
- insufficient memory rejected;
- incompatible runtime rejected;
- privacy violation rejected;
- price/deadline constraint respected;
- explanation deterministic for same inputs.

### Reservation

- lease expiry releases resource;
- commit/expiry race has one winner;
- duplicate release harmless.

### Runtime

- reference output within accepted tolerance;
- no unbounded buffer growth;
- OOM produces structured failure;
- cancellation terminates safely;
- stale placement cannot continue.

### Ledger

- debits equal credits;
- duplicate metering event has one effect;
- retry does not duplicate charge;
- refund cannot exceed attributable charge;
- deterministic rounding.

## Gate-specific tests

### G1

- two heterogeneous devices;
- automatic placement;
- correct shared output;
- duplicate command;
- one forced failure.

### G2

- controlled RTT sweep;
- jitter;
- loss;
- bandwidth limit;
- stage-count sweep;
- transport comparison.

### G4

- auth failures;
- replay;
- cache traversal;
- malicious manifest;
- parser fuzzing;
- update downgrade;
- worker-boundary negative tests.

## Test evidence

A test run should record:

- commit SHA;
- config/schema versions;
- hardware;
- environment;
- model/runtime;
- raw result path;
- pass/fail;
- timing.
