# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, durable orchestration, protocol foundations, and measurable lab/runtime benchmarking  
**Production services/runtime:** none  
**Executable engineering tooling:** inventory + TCP network + llama-bench adapters, durable orchestrator reference, control-envelope parser, initial durable control handlers  
**Public release:** none

## Repository

- repository: `inetconnector/ComputeMesh`
- default branch: `main`
- documentation v0.2: `cf85a47`
- contracts/benchmark bootstrap: `7df5b4e`
- in-memory state machine: `c9733b1`
- transactional persistence/schema admission: `bfea175`
- control envelope/structured errors: `9ed33be`
- TCP network microbenchmark: `197a1ad`
- llama-bench prefill/decode adapter: `6b0356a`
- initial durable control handlers: `9bb4a72`, restricted to documented M0 messages by `b23bf60`

## What exists

- synchronized English/German root READMEs;
- M0 architecture/protocol/security/benchmark/failure/privacy/data-model documentation;
- Draft-2020-12 machine-readable contracts;
- node inventory collector;
- TCP application-level network microbenchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- deterministic Job/Reservation state machine;
- transactional SQLite reference persistence with durable idempotency/revisions/restart recovery/leases;
- SQLite state-store schema v2 migration;
- durable request fingerprints for message type + payload;
- atomic reservation → job + stage binding during `CommitReservation`;
- initial Job/Reservation schema admission;
- transport-neutral control-envelope parser and structured errors;
- message-specific payload contracts and handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`;
- tests for the above components.

## Verified M0 implementation evidence

Previously verified and unchanged:

- inventory collector tests: 3/3 passing;
- TCP network benchmark tests: 4/4 passing;
- llama-bench adapter tests: 6/6 passing;
- generated loopback network result validates against the benchmark-result schema;
- converted llama-bench fixture results validate against the benchmark-result schema.

Current control/orchestration verification before publication:

- existing state/persistence/admission behavior plus new handler/migration regression: 37/37 passing in the assembled local regression workspace;
- protocol control-envelope + payload-contract + schema tests: 15/15 passing;
- relevant Python modules pass `py_compile`;
- migration from the previous SQLite schema is exercised;
- same `request_id` + changed payload is rejected;
- `CommitReservation` binding survives restart;
- missing target job causes full transaction rollback;
- stale revision is returned as a structured retryable conflict;
- expired control envelope creates no durable effect.

Important evidence boundary:

- the TCP benchmark is validated on loopback only, not yet between real nodes;
- the llama-bench adapter is validated against representative upstream JSON/JSONL fixtures, not yet against a real target model/GPU run;
- the three control handlers are transport-neutral application handlers, not an authenticated network service;
- no distributed inference result exists yet.

## What does not exist

- real two-node hardware/network evidence;
- real llama.cpp prefill/decode evidence from the target lab;
- production provider node agent;
- distributed runtime/shared inference;
- gateway/API/scheduler;
- production orchestrator service/database;
- authenticated node sessions/authz;
- remaining node/runtime/artifact protocol handlers;
- registry/verification/billing/telemetry/SDK/UI;
- production release/update system.

## Initial implemented control path

```text
Control document
 -> base-envelope parse/version/expiry checks
 -> message-specific payload schema
 -> operation fingerprint
 -> durable SQLite transaction
 -> revision/state check
 -> exactly-once business effect by request_id
 -> structured result/error
```

Implemented message effects:

- `ReserveCapacity`: `CANDIDATE -> LEASED` with durable lease expiry;
- `CommitReservation`: `LEASED -> COMMITTED` plus atomic job/stage binding;
- `CancelJob`: cancellable job state -> `CANCELLED` with explicit reason/cutoff payload validation.

No authentication or authorization is implied by this path.

## ADR status

Accepted only:

- ADR 0001 — repository bootstrap.

Still proposed:

- ADR 0002 — M1 runtime baseline;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity;
- ADR 0005 — node identity/key lifecycle;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

## Primary blockers

1. No real two-node profiles/cross-node network results exist yet.
2. No real local llama.cpp prefill/decode baseline exists yet.
3. M1 runtime baseline remains unaccepted until the required real two-node spike.
4. Node identity/authentication remains proposed and unimplemented.
5. Only the first three documented control handlers exist; remaining node/runtime/artifact flows are not bound yet.
6. No activation-payload transport benchmark exists yet.
7. WAN viability and verification economics remain unmeasured.
8. No release/update security implementation exists.

## Next actions in order

1. Run `benchmark.py` on two real lab machines and retain both profiles.
2. Run `network_benchmark.py` between those machines in both directions on a trusted LAN.
3. Run `llama_bench_adapter.py` with the selected local GGUF/model and current `llama-bench` on each relevant machine.
4. Compare prefill/decode results and choose the exact two-node M1 spike configuration.
5. Execute the llama.cpp-oriented ADR 0002 runtime spike behind the ComputeMesh boundary.
6. Implement the authenticated node-session skeleton once ADR 0005 details are sufficient.
7. Add the remaining protocol handlers required by the selected M1 runtime path.
8. Add activation-payload-size modes and controlled latency/jitter/loss experiments.
9. Produce the first correct two-node shared inference and begin scheduler calibration.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
