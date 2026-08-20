# ComputeMesh State

**Last updated:** 2026-08-20  
**Phase:** M0 — documentation/architecture bootstrap  
**Production code:** none  
**Public release:** none

This file is a handoff document. It records **facts and current decisions**, not product marketing.

## Repository

Repository:

- `inetconnector/ComputeMesh`
- default branch: `main`
- visibility: public at current inspection; repository was private at initial bootstrap
- bootstrap commit: `6e8d9fe` — `docs: bootstrap ComputeMesh implementation plan`
- follow-up commit: `f214457` — `docs: record repository push state`

## What exists

- project README;
- implementation plan;
- architecture;
- protocol outline/specification;
- threat model;
- security policy;
- contribution guide;
- ADR template/bootstrap ADR;
- directory skeleton.

## What does not exist

No implementation exists yet for:

- node agent;
- runtime worker;
- gateway;
- orchestrator;
- scheduler;
- registry;
- verification;
- billing/ledger;
- telemetry;
- SDK;
- UI;
- deployment;
- tests.

Any wording implying these are operational is incorrect.

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
7. “Confidential compute” must remain disabled as a guarantee until a real attestation/TEE design exists.

## External technology observations checked 2026-08-20

- vLLM documents distributed tensor and pipeline parallel serving, with multi-node configurations aimed at coordinated cluster environments.
- llama.cpp has an RPC backend useful for research, but its upstream documentation still warns that it is proof-of-concept/fragile/insecure for open networks.
- These upstream systems are reference implementations, not the ComputeMesh security boundary.

## M0 ADR backlog

Required decisions:

- M1 runtime baseline;
- serialization format;
- control transport;
- M1 data-plane transport;
- node identity/key lifecycle;
- model/shard manifest format;
- artifact signature/canonicalization;
- reservation semantics;
- telemetry envelope;
- ledger units/precision;
- privacy-tier enforcement.

## Required new engineering artifacts

Before M1:

- node profile schema;
- benchmark result schema;
- model manifest schema;
- shard manifest schema;
- job/reservation schema;
- protocol message schemas;
- two-node lab inventory;
- reproducible benchmark harness;
- threat-model-to-test mapping.

## Primary blockers

1. No runtime selected.
2. No benchmark harness exists.
3. No machine-readable schemas exist.
4. No node identity design exists.
5. No reservation/job state implementation exists.
6. WAN viability remains unmeasured.
7. Verification economics remain unmeasured.
8. No release/update security implementation exists.

## Next actions in order

1. Review/accept documentation v0.2.
2. Select M1 runtime candidate via ADR.
3. Define node profile and benchmark schemas.
4. Define model/shard manifests.
5. Define reservation/job state semantics.
6. Prepare two-node lab.
7. Implement local runtime baseline.
8. Implement authenticated node session skeleton.
9. Implement reservation skeleton.
10. Run first two-node transport microbenchmark.
11. Produce first shared-inference experiment.
12. Compare predicted versus observed timings.

## State-update rule

Update this file after a meaningful change in:

- accepted ADR;
- implemented component;
- milestone/gate status;
- measured result;
- blocker;
- repository/release state.

Do not copy the full architecture or roadmap here. Link to canonical documents instead.

## Bilingual README rule

Root README documentation is permanently maintained in two synchronized files:

- `README.md` — English;
- `README.de.md` — German.

Both include a language selector at the top. Any public-facing change to project status, product boundaries, architecture overview, setup, roadmap, security warnings, or other README-level information must update both files in the same change. Treat README drift as a documentation defect.
