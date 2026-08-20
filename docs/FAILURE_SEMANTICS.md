# ComputeMesh Failure Semantics

**Status:** Draft v0.1

Distributed inference must fail predictably. “Try again” is not a state machine.

## 1. Principles

- every command has identity and expiry;
- every mutation is idempotent;
- a placement is versioned;
- a retry is a new attempt;
- a replan is a new placement revision;
- ambiguous completion is reconciled before settlement;
- failed nodes are assumed to have lost volatile state unless proven otherwise;
- no silent corruption;
- billing is neutral for platform-caused duplicate execution unless policy explicitly assigns cost.

## 2. Failure domains

- client/gateway;
- orchestrator;
- scheduler;
- database;
- registry/artifact source;
- provider agent;
- runtime worker;
- GPU/device;
- peer network;
- verification;
- billing/payment.

## 3. Reservation failures

### Lease expires before commit

Outcome:

- reservation becomes `EXPIRED`;
- no work starts;
- scheduler replans.

### Commit races with expiry

Use revision/transaction semantics. Exactly one outcome wins.

### Node drains after lease

Committed work follows provider policy: finish accepted job if safe, otherwise emit structured failure and replan.

## 4. Artifact failure

Digest mismatch:

- mark artifact invalid;
- do not execute;
- quarantine cache object;
- report integrity failure;
- do not bill inference work.

## 5. Runtime failure before first accepted work

Examples:

- load failure;
- incompatibility;
- OOM during preparation.

Outcome:

- attempt failed;
- scheduler may choose new node;
- provider may be compensated only according to explicit preparation policy, not by ad-hoc self-report.

## 6. Failure during prefill

Options depend on runtime checkpoint ability.

M1 default:

- fail affected attempt;
- restart from safe input state on replacement placement;
- record lost compute;
- do not expose partial invalid result.

Future optimization:

- checkpoint stage state.

## 7. Failure during decode

Decode has sequential state.

If the failed stage's KV/state cannot be reconstructed or migrated safely:

- stop current placement;
- create new placement;
- reconstruct from prompt + accepted generated tokens;
- resume only if deterministic/runtime semantics permit;
- otherwise restart completion.

Never combine logits/state from incompatible placement revisions silently.

## 8. Network partition

A provider that cannot reach the control plane may still have peer traffic. Lease/session expiry defines authority.

After command/session expiry:

- no new billable work;
- stop or drain according to safe runtime policy;
- stale results are not automatically accepted.

## 9. Duplicate result

A duplicate `SegmentResult` with same attempt/result identity:

- returns original acknowledgement;
- creates no duplicate metering.

A conflicting duplicate:

- integrity incident;
- do not settle until investigated.

## 10. Orchestrator restart

Durable job/placement/reservation state must allow recovery.

On restart:

1. load non-terminal jobs;
2. reconcile active reservations;
3. query/await current attempt state;
4. expire stale commands;
5. continue or replan.

## 11. Cancellation

Cancellation uses a monotonic job revision.

After cancellation accepted:

- no new reservations;
- propagate cancellation;
- running kernels may finish their current bounded unit;
- stop future billable units;
- produce final usage reconciliation.

## 12. Billing neutrality

A platform retry caused by:

- duplicate command;
- scheduler bug;
- node failure;
- network failure

must not automatically double customer charges.

Provider compensation for partially useful work is a separate policy and must be derived from explicit metering rules.

## 13. Failure codes

Initial structured codes:

- `NODE_UNREACHABLE`;
- `NODE_DRAINING`;
- `RESERVATION_EXPIRED`;
- `ARTIFACT_INTEGRITY_FAILURE`;
- `RUNTIME_INCOMPATIBLE`;
- `OUT_OF_MEMORY`;
- `DEVICE_FAILURE`;
- `NETWORK_TIMEOUT`;
- `PROTOCOL_ERROR`;
- `STALE_PLACEMENT`;
- `CANCELLED`;
- `VERIFICATION_FAILED`;
- `INTERNAL_CONTROL_PLANE`.

## 14. Chaos acceptance tests

At minimum:

- kill provider before prepare;
- kill provider during prefill;
- kill provider during decode;
- duplicate assignment;
- delay old result until after replan;
- expire reservation at commit boundary;
- restart orchestrator;
- corrupt artifact;
- lose network temporarily;
- cancel during active stream;
- replay ledger event.

Each test asserts state, user outcome, and billing outcome.
