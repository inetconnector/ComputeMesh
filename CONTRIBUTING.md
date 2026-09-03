# Contributing to ComputeMesh

ComputeMesh is an active pre-production engineering project. Contributions should reduce uncertainty, improve measurable correctness, close a defined readiness gate, or make the implementation and its documentation more accurate.

## 1. Contribution principles

- Prefer measured evidence over architecture-by-opinion.
- Keep changes narrow enough to review.
- Separate facts, hypotheses, and decisions.
- Tie implementation to a milestone or workstream.
- Record material decisions as ADRs.
- Preserve security invariants and fail-closed behavior.
- Do not introduce token/ICO/yield mechanics.
- Do not add generic arbitrary-code execution to provider nodes.
- Do not make performance/privacy claims that exceed measured behavior.
- Keep `README.md` and `README.de.md` synchronized for every public-facing project change.
- **Documentation freshness is part of correctness:** a material code, protocol, security, deployment, API, status, or operational change is incomplete until every authoritative document affected by that change is updated in the same branch/PR.

## 2. Documentation freshness invariant

ComputeMesh must not knowingly carry stale authoritative documentation.

For every material change:

1. identify the authoritative docs that describe the changed behavior;
2. update them in the same branch/PR as the implementation;
3. remove or rewrite statements that became false, incomplete, or misleading;
4. distinguish clearly between:
   - merged/available behavior;
   - branch-local or draft implementation;
   - CI/software validation;
   - physical hardware/adversarial validation;
   - production guarantees;
5. update dated status documents to the actual review date;
6. keep English/German paired documents synchronized where both exist;
7. update temporary handoff/status documents after every material milestone, not at the end of a long workstream;
8. never mark a checklist item complete unless its exact stated condition is true.

A PR that changes behavior while leaving an affected authoritative document stale is not ready to merge.

## 3. Before coding

For a non-trivial change, identify:

- problem statement;
- affected milestone/gate;
- acceptance criteria;
- security/privacy impact;
- protocol/data-model impact;
- documentation impact;
- benchmark required;
- rollback or fallback.

If the change creates a new architectural dependency, write or update an ADR first.

## 4. Branching

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

## 5. Commit style

Use scoped imperative messages:

```text
docs: define reservation semantics
protocol: add replay-safe job assignment
scheduler: reject stale node profiles
tests: cover duplicate ledger events
security: constrain artifact cache paths
```

## 6. Definition of done

A change is not complete merely because code compiles or tests pass.

Applicable items:

- behavior implemented;
- unit/integration tests;
- negative/failure tests;
- metrics added;
- protocol/data schema updated;
- all affected authoritative docs updated;
- paired EN/DE docs synchronized where applicable;
- stale status/checklist statements removed;
- ADR updated;
- migration considered;
- security review completed;
- verification commands/results recorded;
- `state.md` updated for meaningful project-state changes;
- temporary project handoffs updated when they are being used as the active continuation source.

## 7. Testing expectations

Changes should map to `docs/TEST_MATRIX.md`.

Minimum examples:

- scheduler: deterministic feasibility and explanation tests;
- protocol: malformed, duplicate, stale, expired, oversized input tests;
- ledger: duplicate/retry/refund invariants;
- runtime: correctness plus benchmark evidence;
- node: drain, restart, update, OOM, GPU reset, network-loss behavior;
- security: authorization and boundary-negative tests.

## 8. Benchmark evidence

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

## 9. Documentation update matrix

| Change | Required docs |
| --- | --- |
| public-facing project/status/setup change | `README.md` **and** `README.de.md`, plus `docs/CURRENT_STATUS.md` / `.de.md` when status changes |
| new service boundary | `ARCHITECTURE.md`, relevant ADR, current-status/handoff if milestone state changes |
| protocol field/message | `PROTOCOL.md`, schema/examples, security docs when binding/trust changes |
| node/job state | `docs/FAILURE_SEMANTICS.md`, data model |
| privacy behavior | `docs/PRIVACY_TIERS.md`, `THREAT_MODEL.md`, `SECURITY.md`, P0 plan where applicable |
| confidential-execution implementation | `docs/P0_CONFIDENTIAL_EXECUTION_PLAN.md`, current status, security/threat-model docs, active private handoff |
| benchmark metric | `docs/BENCHMARK_SPEC.md` |
| security boundary | `THREAT_MODEL.md`, `SECURITY.md`, ADR |
| milestone status | `state.md`, `docs/CURRENT_STATUS.md` / `.de.md`, implementation plan if scope changed |
| deployment/operator contract | setup/deploy/operator docs and environment-variable reference |

## 10. ADR process

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

## 11. Review checklist

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
- Does every authoritative document still match behavior?
- Are dated status docs current?
- Are branch-local/CI/physical/production claims clearly distinguished?
- Are both root READMEs synchronized when public-facing information changed?

## 12. Secrets and local files

Never commit:

- API keys;
- signing keys;
- access tokens;
- `.env` secrets;
- private crash dumps;
- customer prompts/outputs;
- local benchmark caches containing sensitive data.

## 13. Current priority

The current highest-priority engineering work is P0 protected execution and production-readiness closure while preserving the existing public/private control-plane boundary and standard OpenAI-compatible user surface.

In particular:

1. keep the P0 confidential transport/session/metering branch internally consistent and CI-green;
2. wire private confidential provisioning to authenticated provider-control sessions and the protected worker without exposing private ranking internals;
3. complete canonical gateway/bootstrap configuration and fail-closed readiness;
4. integrate a real vendor-supported NVIDIA confidential-compute attestation helper and validate it on supported hardware;
5. keep `CRYPTO_PRIVATE` disabled until a separately validated cryptographic construction exists;
6. run adversarial and physical acceptance before making production confidentiality claims;
7. keep all authoritative documentation synchronized with each of those milestones.
