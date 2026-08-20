# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts and benchmark bootstrap  
**Production services/runtime:** none  
**Executable engineering tooling:** M0 inventory benchmark harness  
**Public release:** none  
**Documentation baseline:** v0.2 accepted and merged to `main`

This file is a handoff document. It records **facts and current decisions**, not product marketing.

## Repository

Repository:

- `inetconnector/ComputeMesh`
- default branch: `main`
- documentation v0.2 commit: `cf85a47` — `docs: expand v0.2 specification and bilingual readmes`
- first M0 implementation branch: `m0/contracts-benchmark-harness`

## What exists

- synchronized English/German root READMEs;
- implementation plan, architecture, protocol, threat model, security policy, contribution guide, ADR process;
- JSON Schema Draft 2020-12 contracts for node profile, benchmark result, model manifest, shard manifest, reservation, and job;
- example model/shard/job/reservation documents;
- standard-library Python inventory benchmark collector;
- benchmark collector unit tests;
- directory skeleton for planned product components.

## What does not exist

No production implementation exists yet for:

- provider node agent;
- runtime worker or distributed inference;
- gateway;
- orchestrator;
- scheduler;
- registry;
- verification;
- billing/ledger;
- telemetry;
- SDK;
- UI;
- deployment/update pipeline.

## Verified M0 implementation evidence

The first executable collector was tested before repository publication of the implementation commit:

- Python unit tests: 3/3 passing;
- JSON syntax checks: all six schemas parse successfully;
- JSON Schema Draft 2020-12 validation: generated node profile and benchmark result pass;
- example model manifest, shard manifest, reservation, and job pass their corresponding schemas.

The collector currently measures inventory only. It is not yet a compute/network performance benchmark.

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

1. The normal dense pipeline data path should transfer stage activations/results; KV cache normally remains with the layers that own it.
2. KV transfer is primarily a migration/recovery/rebalance concern.
3. Prefill and decode need separate performance models.
4. Tensor parallelism is expected to need tightly coupled links; do not plan generic WAN tensor parallelism.
5. The scheduler should use constraint filtering plus predicted multi-objective plan evaluation, not a single permanent score formula.
6. Capacity reservation/lease semantics are required before dispatch.
7. `confidential_compute` remains disabled as a guarantee until a real attestation/TEE design exists.

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

1. M1 runtime baseline is not accepted; the required two-node spike has not been run.
2. Node identity/key lifecycle remains proposed.
3. Control/data transport choices remain unaccepted.
4. No two-node lab profiles exist yet.
5. No local runtime prefill/decode baseline exists yet.
6. No reservation/job state implementation exists beyond schema contracts.
7. WAN viability remains unmeasured.
8. Verification economics remain unmeasured.
9. No release/update security implementation exists.

## Next actions in order

1. Run the inventory harness on two real lab machines and retain profiles/results.
2. Record exact hardware/OS/driver/runtime candidates for the two-node lab.
3. Execute the ADR 0002 llama.cpp-oriented runtime spike without exposing upstream RPC as the ComputeMesh security boundary.
4. Add local runtime prefill/decode benchmark adapters.
5. Implement reservation/job state-machine skeleton against the current schemas.
6. Implement authenticated node-session skeleton after node-identity details are selected.
7. Run the first activation-transport microbenchmark.
8. Produce the first correct two-node shared-inference experiment.
9. Compare predicted versus observed timings and update the scheduler model.

## State-update rule

Update this file after a meaningful change in:

- accepted ADR;
- implemented component/tool;
- milestone/gate status;
- measured result;
- blocker;
- repository/release state.

Do not copy the full architecture or roadmap here. Link to canonical documents instead.

## Bilingual README rule

Root README documentation is permanently maintained in two synchronized files:

- `README.md` — English;
- `README.de.md` — German.

Any public-facing change to project status, product boundaries, architecture overview, setup, roadmap, security warnings, or other README-level information must update both files in the same change. Treat README drift as a documentation defect.
