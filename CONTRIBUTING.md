# Contributing to ComputeMesh

ComputeMesh is in M0. The goal of contributions is to reduce uncertainty, improve measurable correctness, or advance a defined feasibility gate.

## 1. Contribution principles

- Prefer measured evidence over architecture-by-opinion.
- Keep changes narrow enough to review.
- Separate facts, hypotheses, and decisions.
- Tie implementation to a milestone or workstream.
- Record material decisions as ADRs.
- Preserve V1 security invariants.
- Do not introduce token/ICO/yield mechanics.
- Do not add generic arbitrary-code execution to provider nodes.
- Do not make performance/privacy claims that exceed measured behavior.
- Keep `README.md` and `README.de.md` synchronized for every public-facing project change.

## 2. Before coding

For a non-trivial change, identify:

- problem statement;
- affected milestone/gate;
- acceptance criteria;
- security/privacy impact;
- protocol/data-model impact;
- benchmark required;
- rollback or fallback.

If the change creates a new architectural dependency, write or update an ADR first.

## 3. Branching

Use one focused branch per change.

Suggested names:

```text
docs/protocol-envelope
runtime/llama-m1-prototype
scheduler/reservation-model
security/node-key-lifecycle
tests/job-idempotency
```

Do not mix unrelated formatting, refactors, and feature changes.

## 4. Commit style

Use scoped imperative messages:

```text
docs: define reservation semantics
protocol: add replay-safe job assignment
scheduler: reject stale node profiles
tests: cover duplicate ledger events
security: constrain artifact cache paths
```

## 5. Definition of done

A change is not complete merely because code compiles.

Applicable items:

- behavior implemented;
- unit/integration tests;
- negative/failure tests;
- metrics added;
- protocol/data schema updated;
- docs updated;
- ADR updated;
- migration considered;
- security review completed;
- verification commands/results recorded;
- `state.md` updated for meaningful project-state changes.

## 6. Testing expectations

Changes should map to `docs/TEST_MATRIX.md`.

Minimum examples:

- scheduler: deterministic feasibility and explanation tests;
- protocol: malformed, duplicate, stale, expired, oversized input tests;
- ledger: duplicate/retry/refund invariants;
- runtime: correctness plus benchmark evidence;
- node: drain, restart, update, OOM, GPU reset, network-loss behavior;
- security: authorization and boundary-negative tests.

## 7. Benchmark evidence

Performance-related PRs should state:

- hardware;
- OS/driver;
- runtime/build;
- model and quantization;
- batch/context;
- network conditions;
- warm/cold state;
- command/script;
- raw result artifact location;
- summary statistics.

Do not publish “X tokens/s” without conditions.

## 8. Documentation update matrix

| Change | Required docs |
| --- | --- |
| public-facing project/status/setup change | `README.md` **and** `README.de.md` in the same change |
| new service boundary | `ARCHITECTURE.md`, ADR |
| protocol field/message | `PROTOCOL.md`, schema/examples |
| node/job state | `docs/FAILURE_SEMANTICS.md`, data model |
| privacy behavior | `docs/PRIVACY_TIERS.md`, threat model |
| benchmark metric | `docs/BENCHMARK_SPEC.md` |
| security boundary | `THREAT_MODEL.md`, `SECURITY.md`, ADR |
| milestone status | `state.md`, implementation plan if scope changed |

## 9. ADR process

Use `docs/adr/0000-adr-template.md`.

An ADR should contain:

- decision drivers;
- considered options;
- decision;
- consequences;
- security/privacy impact;
- operational impact;
- verification;
- rollback/revisit trigger.

Accepted ADRs are changed by superseding ADR, not silent history rewrite, except spelling/clarity fixes.

## 10. Review checklist

Reviewers should ask:

- Is the change correct?
- Is behavior deterministic under retry?
- Is failure observable?
- Does it widen the provider attack surface?
- Does it increase data exposure?
- Are billing effects neutral under failure?
- Are inputs bounded and validated?
- Can the scheduler explain the result?
- Is the benchmark reproducible?
- Does the code assume LAN/datacenter properties on WAN links?
- Does the documentation still match behavior?
- Are both root READMEs synchronized when public-facing information changed?

## 11. Secrets and local files

Never commit:

- API keys;
- signing keys;
- access tokens;
- `.env` secrets;
- private crash dumps;
- customer prompts/outputs;
- local benchmark caches containing sensitive data.

## 12. Current priority

M0 priorities:

1. ADRs for runtime, transport, identity, manifests, telemetry, ledger units;
2. benchmark specification;
3. node profile schema;
4. model/shard manifest schema;
5. reservation and state semantics;
6. two-node lab plan;
7. first runtime prototype;
8. threat-model closure for M1.
