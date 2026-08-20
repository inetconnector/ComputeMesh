# ComputeMesh Implementation Plan

**Status:** Execution plan v0.2  
**Current phase:** M0 — architecture and feasibility  
**Planning principle:** technical gates before marketplace scale

## 1. Mission

Build and validate a distributed inference fabric where a client can use a model that does not fit on the client by automatically placing approved inference work across heterogeneous remote compute.

The mission is intentionally narrower than “distributed cloud”:

- inference first;
- approved runtimes/models only;
- no arbitrary user code;
- measured network-aware placement;
- failure and billing semantics designed from the start.

## 2. North Star versus first proof

### North Star

A user with limited local resources selects a large model and receives an interactive result without manually managing remote machines.

### M1 proof

Do not start with a >200 GB requirement. M1 only needs to prove the architecture:

- two different GPU/device profiles;
- one model path spanning both;
- automatic placement;
- no manual shard script during the measured run;
- correct output;
- reproducible metrics;
- clean failure reporting.

### Later demonstrator

A 70B-class or otherwise clearly “larger than local VRAM” demonstrator is a later milestone after the M1/M2 performance model exists.

## 3. Product boundaries

### In scope for V1

- distributed approved-model inference;
- provider node enrollment and benchmarking;
- signed model/shard metadata;
- topology-aware placement;
- reservations;
- runtime workers;
- failure-aware jobs;
- OpenAI-compatible API;
- privacy/policy constraints;
- verification/reputation;
- fiat accounting and settlement;
- Windows-first provider UX.

### Explicitly out of scope for V1

- arbitrary customer code;
- arbitrary Docker/VM jobs;
- generic GPU rental;
- user-uploaded native kernels;
- token/ICO settlement;
- “confidential” consumer compute without a real attestation design;
- broad public launch before technical/security gates pass.

## 4. Hypotheses

| ID | Hypothesis | How to falsify |
| --- | --- | --- |
| H1 | Heterogeneous devices can share one model path automatically | scheduler/runtime cannot produce correct shared inference |
| H2 | At least one useful distributed mode survives real network conditions | all tested interactive/batch/MoE modes are uncompetitive or unstable |
| H3 | Dynamic profiling predicts placement well enough to avoid pathological plans | prediction error remains too high for reliable scheduling |
| H4 | Risk-based verification can reduce fraud/error at acceptable overhead | required duplicate work destroys economics |
| H5 | Provider software can be safe and low-maintenance | host risk/support burden remains unacceptable |
| H6 | API abstraction can hide most placement complexity | callers need topology/runtime-specific manual tuning for normal use |
| H7 | Unit economics can compete in at least one segment | all-in cost exceeds alternatives without differentiated value |

Each hypothesis must have measurements, not just prototype anecdotes.

## 5. Gates

### G0 — Architecture ready for implementation

Pass when:

- required M1 ADRs are accepted;
- node/job/reservation state semantics are documented;
- benchmark schema exists;
- model/shard manifest draft exists;
- threat model covers M1;
- two-node lab is defined;
- M1 definition of done is testable.

### G1 — Shared heterogeneous execution

Pass when a reproducible test proves:

- at least two differing device profiles participate;
- scheduler produces placement from machine-readable profiles/manifests;
- artifacts are prepared and verified;
- inference completes correctly;
- metrics separate preparation, queue, transfer, compute, and end-to-end latency;
- duplicate/retry behavior does not corrupt job state.

### G2 — Network viability

Run across:

- same host/multi-GPU baseline;
- LAN;
- controlled latency/jitter/loss;
- at least two real physical sites.

Record separately for prefill and decode:

- TTFT;
- inter-token latency distribution;
- tokens/s;
- bytes/token by stream class;
- stage utilization;
- queue/bubble time;
- retransmission/recovery;
- failure rate.

Outcome categories:

- interactive viable;
- regional only;
- batch viable;
- expert/MoE promising;
- not viable with current runtime/partition strategy.

### G3 — Economic viability

Pass only for a defined workload segment, not in the abstract.

Model:

```text
customer price
- provider compute payout
- provider/network payout if any
- verification overhead
- payment fees
- refund/failure reserve
- platform infra
= contribution margin
```

Inputs must come from measured runtime and real pricing assumptions with sensitivity ranges.

### G4 — Security/trust viability

Pass when:

- provider workload boundary is enforced;
- node identity/key lifecycle is defined;
- state-changing operations are replay-safe;
- artifact integrity is enforced;
- public-compute confidentiality limits are explicit;
- verification policy exists;
- protocol parsers have negative/fuzz coverage;
- update signing/rollback design is credible.

### G5 — Provider operability

Pass when a non-developer test user can:

- install;
- enroll;
- see resource use;
- set limits;
- become ready;
- execute work;
- drain;
- recover from reboot/update;
- export diagnostics;
- uninstall cleanly.

## 6. Workstreams

### WS1 — Architecture and ADRs

Deliver:

- architecture v0.2+;
- protocol v0.2+;
- ADRs;
- dependency map;
- architecture test plan.

Done when M1 has no material undefined interface that blocks implementation.

### WS2 — Node profile and benchmark harness

Deliver:

- hardware inventory schema;
- runtime capability schema;
- benchmark suite;
- network probe;
- profile freshness rules;
- benchmark result storage.

Done when two machines produce comparable machine-readable profiles and results.

### WS3 — Registry and artifact model

Deliver:

- model manifest;
- shard manifest;
- content digest format;
- signatures;
- local cache contract;
- artifact preparation workflow.

Done when a node can prove it prepared exactly the artifact requested.

### WS4 — Runtime integration

Start with one narrow runtime path.

Deliver:

- local baseline;
- remote stage prototype;
- prefill/decode instrumentation;
- bounded activation stream;
- correctness test;
- failure reporting.

Done when two nodes produce one correct shared inference under controlled conditions.

### WS5 — Scheduler, reservations, topology

Deliver:

- hard-constraint engine;
- candidate generation;
- reservation lease;
- simple predicted latency model;
- placement explanation;
- replan entry point.

Done when the M1 placement contains no hand-authored node/shard choice.

### WS6 — Job orchestration and failure semantics

Deliver:

- job state machine;
- placement revision;
- cancellation;
- retry/replan;
- reservation expiry;
- idempotency store;
- failure attribution.

Done when repeated commands, node loss, and orchestrator restart produce deterministic outcomes.

### WS7 — Verification and reputation

M1 does not require sophisticated proof-of-inference.

Deliver initially:

- node probation;
- canary framework;
- sampled redundancy hook;
- verification result schema;
- reputation evidence history.

Done when verification policy can be attached to a job and affects settlement/scheduling.

### WS8 — Billing and ledger

Do not integrate payouts before execution events stabilize.

Deliver:

- billable event model;
- double-entry ledger;
- precision/units ADR;
- retry/refund semantics;
- provider earning allocation simulation.

Done when the same event log deterministically regenerates the same financial result.

### WS9 — API and UX

Deliver:

- OpenAI-compatible API skeleton;
- ComputeMesh namespaced policy;
- job status;
- provider node status;
- drain/limits;
- diagnostics.

Done when a demo does not require direct scheduler/runtime manipulation by the user.

### WS10 — Security and release engineering

Deliver:

- threat model;
- auth/key lifecycle;
- workload boundary;
- artifact/update signing;
- rollback/revocation plan;
- SBOM/provenance plan;
- incident process.

Done when G4 is satisfied before public alpha.

## 7. Milestones

### M0 — Foundation

**Entry:** repository bootstrap.  
**Exit:** G0.

Tasks:

1. accept or reject initial runtime ADR;
2. choose protocol serialization candidate;
3. choose M1 transport experiment;
4. define node identity;
5. define model/shard manifests;
6. define node profile;
7. implement benchmark spec;
8. define reservation/job state machines;
9. define telemetry envelope;
10. define ledger units;
11. prepare two-node lab;
12. close M1 threat-model blockers.

### M1 — Two-node shared inference

Goal: prove end-to-end architecture with the smallest useful model/runtime combination.

Required outputs:

- node A/B profiles;
- placement plan;
- reservation trace;
- artifact trace;
- inference trace;
- benchmark report;
- correctness result;
- failure result;
- known limitations.

No public performance claim until the result is reproducible.

### M2 — Heterogeneous placement

Goal: move from two known machines to dynamic selection among multiple different profiles.

Add:

- capacity freshness;
- more than one feasible plan;
- predicted versus observed latency;
- memory safety margin;
- slow-node sensitivity;
- automatic rejection reasons.

### M3 — Network characterization

Goal: decide what the product can realistically do over real networks.

Experiments:

- local multi-GPU baseline;
- 1/2.5/10+ GbE LAN where available;
- latency injection;
- jitter/loss injection;
- two-site WAN;
- transport comparison;
- stage-count sensitivity;
- activation encoding/quantization experiments if justified.

Decision output must name the winning workload class.

### M4 — Large-model demonstrator

Goal: client uses a model clearly beyond local capacity.

Requirements:

- no manual placement;
- reproducible model manifest;
- measured ready time;
- measured TTFT/decode;
- cost estimate;
- failure behavior;
- visible policy/placement summary.

### M5 — Failure recovery

Goal: deliberately remove a participating node.

Test:

- before prefill;
- during prefill;
- during decode;
- after provider result but before final acknowledgement.

For each, document:

- expected state transition;
- user-visible behavior;
- data/state reconstruction;
- billable effect;
- recovery time.

### M6 — Private alpha

Only after G1-G5 pass for a deliberately narrow supported configuration.

## 8. M0 implementation sequence

Recommended order:

```text
ADRs
  -> schemas
  -> benchmark harness
  -> node profile
  -> node session/enrollment
  -> reservations
  -> runtime local baseline
  -> two-node data plane
  -> shared inference
  -> scheduler automation
  -> failure tests
```

Reason: scheduler work without reliable profiles/runtime measurements creates false precision.

## 9. Initial runtime evaluation

Evaluate at least:

- llama.cpp remote/RPC-related mechanisms as a research baseline;
- vLLM multi-node parallelism as a datacenter-oriented reference;
- a minimal custom stage transport if needed for M1.

Do not expose an upstream experimental RPC service directly as the ComputeMesh public node protocol. Upstream components are implementation details behind the ComputeMesh trust boundary.

Evaluation criteria:

- Windows feasibility;
- model coverage;
- controllable partition boundaries;
- instrumentation;
- dynamic heterogeneous support;
- transport control;
- failure handling;
- security boundary;
- license/integration cost;
- ability to separate prefill/decode measurements.

## 10. Benchmark plan

Use `docs/BENCHMARK_SPEC.md`.

Core suites:

- device inventory;
- memory bandwidth;
- compute GEMM;
- quantized matmul;
- attention/prefill;
- decode;
- KV allocation/growth;
- host-device transfer;
- network RTT/throughput;
- activation transfer;
- artifact prepare/load;
- failure/reconnect.

All metrics need schema version and test conditions.

## 11. Data model

See `docs/DATA_MODEL.md`.

Core entities:

- users/principals;
- nodes;
- devices;
- node profiles;
- benchmark runs;
- models;
- model versions;
- artifacts/shards;
- network observations;
- capacity offers;
- reservations;
- jobs;
- placements;
- stages;
- attempts;
- verification results;
- reputation evidence;
- metering events;
- ledger entries;
- settlements.

Avoid one overloaded `hardware` or `ledger` table with ambiguous semantics.

## 12. Reliability principles

- leases expire;
- retries are explicit attempts;
- placement has revision;
- commands expire;
- duplicate events dedupe;
- recovery never assumes a failed node retained state;
- billable work maps to accepted execution evidence;
- user cancellation is propagated;
- stale provider responses cannot overwrite a newer placement.

## 13. Metrics

### User-experience

- time to model ready;
- TTFT;
- inter-token p50/p95/p99;
- end-to-end tokens/s;
- completion success rate.

### Runtime

- prefill tokens/s;
- stage compute time;
- activation transfer time;
- bytes/token;
- KV bytes/token;
- GPU utilization;
- memory headroom;
- pipeline bubble ratio.

### Scheduler

- planning latency;
- feasibility rejection reasons;
- prediction error;
- replan frequency;
- reservation failure rate.

### Reliability

- node availability;
- disconnect rate;
- attempt failure rate;
- recovery time;
- restart rate;
- stale-message rate.

### Verification

- sample rate;
- disagreement rate;
- canary failure;
- verification overhead.

### Economics

- provider resource seconds;
- bytes transferred;
- customer cost/token/request;
- verification cost;
- refund rate;
- contribution margin.

## 14. Test strategy

See `docs/TEST_MATRIX.md`.

Required layers:

- unit;
- property;
- schema;
- protocol negative/fuzz;
- integration;
- distributed;
- performance;
- chaos;
- security;
- ledger reconciliation.

## 15. Risk register

| Risk | Early signal | Mitigation / pivot |
| --- | --- | --- |
| WAN stage latency dominates decode | inter-token latency rises roughly with stage RTT | regionalize, fewer stages, batch, MoE |
| heterogeneous runtime incompatibility | frequent feasibility rejection/runtime crashes | narrow supported matrix |
| profile prediction is unstable | high observed/predicted error | online calibration, uncertainty penalties |
| consumer availability too poor | high mid-job disconnect | shorter leases, replication, datacenter mix |
| artifact prep dominates UX | long cold-start | cache-aware placement, prefetch |
| verification too costly | duplicate cost high | risk-based sampling, supported workload tiers |
| confidentiality demand incompatible with public nodes | users require protected prompts | datacenter/confidential tier only |
| Windows runtime limits performance/features | missing backend/network feature | node-agent Windows + remote Linux worker tier, or narrow V1 |
| payment overhead too high | minimum job cost dominates | aggregate settlement/credits |
| support burden too high | driver/install failures | supported hardware matrix, diagnostics |
| model license restrictions | distribution prohibited | registry policy and allowlist |
| update compromise | signing/process weakness | release key isolation, provenance, revocation |

## 16. 90-day interpretation

The original 90-day structure is an aspiration, not a promise. Gate quality has priority over calendar progression.

Suggested allocation:

- Days 1-14: M0/G0;
- Days 15-35: M1/G1;
- Days 36-55: M2;
- Days 56-70: M3/G2;
- Days 71-82: M4;
- Days 83-90: M5 plus G3/G4 gap analysis.

If G1 slips, do not start marketplace/billing UI to preserve the calendar.

## 17. Definition of public-alpha readiness

A private/public alpha requires:

- supported hardware/runtime matrix;
- signed installer/update;
- rollback/revocation;
- node workload boundary;
- authn/authz;
- artifact verification;
- privacy tiers that match reality;
- rate/budget limits;
- failure semantics;
- ledger correctness;
- provider controls;
- diagnostics;
- status/incident process;
- minimum test matrix;
- measured performance disclosure;
- legal/privacy/payment review.

## 18. Immediate next actions

1. Accept the documentation v0.2 baseline.
2. Decide the first M1 runtime ADR.
3. Decide node identity/key lifecycle.
4. Implement JSON/YAML schema drafts for node profile and model manifest.
5. Build benchmark harness skeleton.
6. Define two-node hardware inventory.
7. Run local single-node baseline.
8. Prototype reservation/job state store.
9. Run first remote activation transport microbenchmark.
10. Update `state.md` with measured facts only.
