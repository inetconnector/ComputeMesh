# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, durable orchestration, protocol foundations, and measurable lab/runtime benchmarking  
**Production services/runtime:** none  
**Executable engineering tooling:** inventory + TCP network + llama-bench adapters, orchestrator reference, control-envelope parser  
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

## What exists

- synchronized English/German root READMEs;
- M0 architecture/protocol/security/benchmark/failure/privacy/data-model documentation;
- Draft-2020-12 machine-readable contracts;
- node inventory collector;
- TCP application-level network microbenchmark;
- llama.cpp llama-bench prefill/decode adapter;
- deterministic Job/Reservation state machine;
- transactional SQLite reference persistence with durable idempotency/revisions/restart recovery/leases;
- initial Job/Reservation schema admission;
- transport-neutral control-envelope parser and structured errors;
- tests for the above components.

## Verified M0 implementation evidence

- inventory collector tests: 3/3 passing;
- TCP network benchmark tests: 4/4 passing;
- llama-bench adapter tests: 6/6 passing;
- generated loopback network result validates against the benchmark-result schema;
- converted llama-bench fixture results validate against the benchmark-result schema;
- orchestrator state/persistence/admission: 21/21 passing;
- protocol envelope/schema block: 10/10 passing;
- relevant Python modules pass `py_compile`.

Important evidence boundary:

- TCP network benchmark is validated on loopback only, not yet between real nodes;
- llama-bench adapter is validated against representative upstream JSON/JSONL fixtures, not yet against a real local model/GPU run;
- no distributed inference result exists yet.

## What does not exist

- real two-node hardware/network evidence;
- real llama.cpp prefill/decode evidence from the target lab;
- production provider node agent;
- distributed runtime/shared inference;
- gateway/API/scheduler;
- production orchestrator service/database;
- authenticated node sessions/authz;
- message-specific protocol handlers;
- registry/verification/billing/telemetry/SDK/UI;
- production release/update system.

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
4. Node identity/authentication remains proposed/unimplemented.
5. Message-specific protocol handlers are missing.
6. No activation-payload transport benchmark exists yet.
7. WAN viability and verification economics remain unmeasured.
8. No release/update security implementation exists.

## Next actions in order

1. Run `benchmark.py` on two real lab machines and retain both profiles.
2. Run `network_benchmark.py` between those machines in both directions on a trusted LAN.
3. Run `llama_bench_adapter.py` with the selected local GGUF/model and current llama-bench on each relevant machine.
4. Compare prefill/decode results and choose the exact two-node M1 spike configuration.
5. Execute the llama.cpp-oriented ADR 0002 runtime spike behind the ComputeMesh boundary.
6. Add message-specific payload schemas/handlers and bind protocol request IDs to durable state effects.
7. Implement authenticated node-session skeleton once ADR 0005 details are sufficient.
8. Add activation-payload-size modes and controlled latency/jitter/loss experiments.
9. Produce first correct two-node shared inference and begin scheduler calibration.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
