# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, durable orchestration, protocol foundations, and measurable lab networking  
**Production services/runtime:** none  
**Executable engineering tooling:** inventory benchmark + TCP network benchmark + orchestrator reference + control-envelope parser  
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

## What exists

- synchronized English/German root READMEs;
- M0 architecture/protocol/security/benchmark/failure/privacy/data-model documentation;
- Draft-2020-12 contracts including control envelope and structured errors;
- node inventory collector;
- TCP application-level network microbenchmark;
- deterministic Job/Reservation state machine;
- transactional SQLite reference persistence with durable idempotency/revisions/restart recovery/leases;
- initial Job/Reservation schema admission;
- transport-neutral control-envelope parser and structured errors;
- tests for the above components.

## Verified M0 implementation evidence

- original inventory collector tests: 3/3 passing;
- orchestrator state/persistence/admission: 21/21 passing;
- protocol envelope/schema block: 10/10 passing;
- TCP network benchmark unit/loopback tests: 4/4 passing;
- generated loopback `tcp_network_path` result validated against `benchmark_result.schema.json` Draft 2020-12;
- relevant Python modules pass `py_compile`.

The TCP benchmark currently proves the tool on loopback only. It does **not** yet provide real two-node LAN/WAN evidence.

## What does not exist

- production provider node agent;
- runtime worker/distributed inference;
- gateway/API;
- scheduler;
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

1. No real two-node profiles or cross-node network results exist yet.
2. No local runtime prefill/decode baseline exists yet.
3. M1 runtime baseline remains unaccepted until the two-node spike.
4. Node identity/authentication remains proposed/unimplemented.
5. Message-specific protocol handlers are missing.
6. No activation-payload transport benchmark exists yet.
7. WAN viability and verification economics remain unmeasured.
8. No release/update security implementation exists.

## Next actions in order

1. Run `benchmark.py` on two real lab machines and retain both profiles.
2. Run `network_benchmark.py` between those machines on a trusted LAN in both directions.
3. Add local runtime prefill/decode benchmark adapter with reproducible result records.
4. Execute the llama.cpp-oriented ADR 0002 runtime spike behind the ComputeMesh boundary.
5. Add message-specific payload schemas/handlers and bind protocol request IDs to durable state effects.
6. Implement authenticated node-session skeleton once ADR 0005 details are sufficient.
7. Add activation-payload-size benchmark modes and controlled latency/jitter/loss experiments.
8. Produce the first correct two-node shared-inference experiment.
9. Compare predicted versus observed timings and begin scheduler calibration.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
