# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, benchmark bootstrap, and durable orchestration semantics  
**Production services/runtime:** none  
**Executable engineering tooling:** inventory benchmark + orchestrator reference implementation  
**Public release:** none  
**Documentation baseline:** v0.2 accepted and merged to `main`

This file is a handoff document. It records **facts and current decisions**, not product marketing.

## Repository

- repository: `inetconnector/ComputeMesh`
- default branch: `main`
- documentation v0.2 commit: `cf85a47`
- first M0 contracts/benchmark commit: `7df5b4e`
- in-memory state-machine commit: `c9733b1`
- transactional persistence/schema-admission commit: `bfea175`

## What exists

- synchronized English/German root READMEs;
- implementation plan, architecture, protocol, threat model, security policy, contribution guide, ADR process;
- JSON Schema Draft 2020-12 contracts for node profile, benchmark result, model manifest, shard manifest, reservation, and job;
- example model/shard/job/reservation documents;
- standard-library Python inventory benchmark collector and tests;
- deterministic in-memory reservation/job state machine;
- transactional SQLite M0 state store with durable idempotency, revisions, restart recovery, lease persistence/expiry, and stale-writer rejection;
- Job/Reservation JSON Schema validation and initial durable admission;
- orchestrator tests covering state-machine, persistence/concurrency/restart, and contract admission.

## What does not exist

No production implementation exists yet for:

- provider node agent;
- runtime worker or distributed inference;
- gateway;
- scheduler;
- production orchestrator network service;
- production/PostgreSQL persistence adapter;
- registry;
- verification;
- billing/ledger;
- telemetry;
- SDK;
- UI;
- deployment/update pipeline.

## Verified M0 implementation evidence

Current verified evidence accumulated from the implementation work:

- benchmark collector unit tests: 3/3 passing (collector unchanged by the persistence work);
- orchestrator state-machine tests: 8/8 passing;
- SQLite persistence/concurrency/restart tests: 8/8 passing;
- contract/admission tests: 5/5 passing;
- orchestrator total: **21/21 passing**;
- orchestrator modules pass Python `py_compile`;
- all six JSON schemas parse successfully;
- generated node profile and benchmark result validated against Draft 2020-12 schemas;
- example model, shard, reservation, and job documents validated against their schemas.

The benchmark collector currently measures inventory only. It is not yet a compute/network performance benchmark.

## Fixed V1 constraints

Until superseded by an ADR:

- no arbitrary customer code on provider nodes;
- Windows-first provider UX;
- approved inference workloads only;
- model/runtime-aware scheduling;
- hard policy/compatibility constraints before optimization;
- fiat-denominated accounting first;
- public compute does not imply confidential execution;
- content-addressed verified model artifacts;
- duplicate/retry-safe business effects;
- performance claims require reproducible evidence.

## Important architecture clarifications

1. Dense pipeline execution normally transfers stage activations/results; KV cache remains with owning layers.
2. KV transfer is primarily migration/recovery/rebalance.
3. Prefill and decode need separate performance models.
4. Tensor parallelism is expected to need tightly coupled links; generic WAN TP is not assumed.
5. Scheduling uses hard constraints plus predicted multi-objective evaluation, not a permanent scalar formula.
6. Capacity reservation/lease semantics are required before dispatch.
7. `confidential_compute` remains disabled as a guarantee until a real attestation/TEE design exists.
8. SQLite is an M0 reference persistence adapter, not a production database decision.

## ADR status

Accepted:

- ADR 0001 — repository bootstrap from blueprint.

Still proposed:

- ADR 0002 — M1 runtime baseline;
- ADR 0003 — control/data transport evaluation;
- ADR 0004 — model/artifact identity;
- ADR 0005 — node identity/key lifecycle;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

Do not describe proposed ADRs as accepted decisions.

## Current machine-readable contracts

Under `protocol/schemas/`:

- `node_profile.schema.json`;
- `benchmark_result.schema.json`;
- `model_manifest.schema.json`;
- `shard_manifest.schema.json`;
- `reservation.schema.json`;
- `job.schema.json`.

These are M0 drafts and are not wire-stable.

## Primary blockers

1. No two-node lab profiles exist yet.
2. M1 runtime baseline is not accepted; the required two-node spike has not been run.
3. No local runtime prefill/decode baseline exists yet.
4. Node identity/key lifecycle remains proposed.
5. Control/data transport choices remain unaccepted.
6. Orchestrator semantics are durable in the SQLite reference, but network protocol handlers, authentication/authorization, and a production DB adapter do not exist.
7. WAN viability remains unmeasured.
8. Verification economics remain unmeasured.
9. No release/update security implementation exists.

## Next actions in order

1. Run the inventory harness on two real lab machines and retain profiles/results.
2. Record exact hardware/OS/driver/runtime candidates for the two-node lab.
3. Add a local runtime prefill/decode benchmark adapter with reproducible result records.
4. Execute the ADR 0002 llama.cpp-oriented runtime spike without exposing upstream RPC as the ComputeMesh security boundary.
5. Define concrete protocol handlers around the durable Job/Reservation semantics.
6. Implement authenticated node-session skeleton after node-identity details are sufficiently specified.
7. Run the first activation-transport microbenchmark.
8. Produce the first correct two-node shared-inference experiment.
9. Compare predicted versus observed timings and update the scheduler model.

## Bilingual README rule

Root README documentation is permanently maintained in two synchronized files:

- `README.md` — English;
- `README.de.md` — German.

Any public-facing change to project status, product boundaries, architecture overview, setup, roadmap, security warnings, or other README-level information must update both files in the same change. Treat README drift as a documentation defect.
