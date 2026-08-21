# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, benchmark bootstrap, durable orchestration, and protocol foundations  
**Production services/runtime:** none  
**Executable engineering tooling:** inventory benchmark + orchestrator reference + control-envelope parser  
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
- control-envelope/structured-error commit: `9ed33be`

## What exists

- synchronized English/German root READMEs;
- architecture, protocol, threat model, security policy, implementation plan, contribution guide, ADR process;
- Draft 2020-12 schemas for node profile, benchmark result, model/shard manifests, reservation, job, common control envelope, and structured error;
- standard-library Python inventory benchmark collector;
- deterministic Job/Reservation state machine;
- transactional SQLite M0 state store with durable idempotency, revisions, restart recovery, lease persistence/expiry, and stale-writer rejection;
- Job/Reservation JSON Schema validation and initial durable admission;
- transport-neutral common control-envelope parser;
- structured protocol-error model;
- tests for benchmark, orchestrator state/persistence/admission, protocol envelope, and new protocol schemas.

## What does not exist

No production implementation exists yet for:

- provider node agent;
- runtime worker or distributed inference;
- gateway;
- scheduler;
- production orchestrator network service;
- production/PostgreSQL persistence adapter;
- authenticated node sessions/authz;
- message-specific node/orchestrator payload handlers;
- registry;
- verification;
- billing/ledger;
- telemetry;
- SDK;
- UI;
- deployment/update pipeline.

## Verified M0 implementation evidence

- benchmark collector unit tests: 3/3 passing (collector unchanged by later work);
- orchestrator state-machine tests: 8/8 passing;
- SQLite persistence/concurrency/restart tests: 8/8 passing;
- contract/admission tests: 5/5 passing;
- orchestrator total: **21/21 passing**;
- control-envelope/parser tests: 8/8 passing;
- control-envelope/error schema tests: 2/2 passing;
- protocol block total: **10/10 passing**;
- orchestrator and protocol modules pass Python `py_compile`;
- existing schema/example validation from the contracts bootstrap remains passing.

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

## Protocol status

The common envelope now has executable semantics and a schema. It enforces base structural/version/time constraints only.

Still missing:

- authentication and authorization;
- capability negotiation behavior beyond major-version compatibility;
- message-specific schemas/handlers;
- replay dedupe binding between protocol request IDs and durable state;
- transport binding;
- node session lifecycle implementation.

## Primary blockers

1. No two-node lab profiles exist yet.
2. M1 runtime baseline is not accepted; the required two-node spike has not been run.
3. No local runtime prefill/decode baseline exists yet.
4. Node identity/key lifecycle remains proposed.
5. Control/data transport choices remain unaccepted.
6. Message-specific protocol handlers and authenticated sessions do not exist.
7. WAN viability remains unmeasured.
8. Verification economics remain unmeasured.
9. No release/update security implementation exists.

## Next actions in order

1. Run the inventory harness on two real lab machines and retain profiles/results.
2. Record exact hardware/OS/driver/runtime candidates for the two-node lab.
3. Add a local runtime prefill/decode benchmark adapter with reproducible result records.
4. Execute the ADR 0002 llama.cpp-oriented runtime spike without exposing upstream RPC as the ComputeMesh security boundary.
5. Add message-specific payload schemas/handlers around the durable Job/Reservation semantics.
6. Bind protocol `request_id`/revision semantics to durable idempotency effects.
7. Implement authenticated node-session skeleton after node-identity details are sufficiently specified.
8. Run the first activation-transport microbenchmark.
9. Produce the first correct two-node shared-inference experiment.
10. Compare predicted versus observed timings and update the scheduler model.

## Bilingual README rule

Root README documentation is permanently maintained in two synchronized files:

- `README.md` — English;
- `README.de.md` — German.

Any public-facing change to project status, product boundaries, architecture overview, setup, roadmap, security warnings, or other README-level information must update both files in the same change. Treat README drift as a documentation defect.
