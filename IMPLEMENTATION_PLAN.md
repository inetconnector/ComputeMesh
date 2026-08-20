# ComputeMesh Implementation Plan

This plan translates `ComputeMesh_Blueprint_v1.0.pdf` into an execution-ready engineering program. The objective is to prove whether heterogeneous, distributed AI inference can feel like one virtual machine while staying secure, measurable, and economically credible.

## 1. North Star

Build a system where a small local GPU can run a model that exceeds local VRAM by automatically using verified network compute.

Primary proof:

```text
8 GB local GPU -> network compute -> model requiring >200 GB memory -> interactive result
```

The first public-quality proof is not node count. It is a reliable user experience where model selection, shard placement, execution, failover, and billing are abstracted away from the user.

## 2. Product Boundaries

In scope for V1:

- distributed inference for approved model workloads
- Windows-first provider node
- automatic hardware discovery and benchmarking
- model registry and signed shard manifests
- topology-aware scheduling
- adaptive verification and reputation
- fiat billing with internal ledger
- OpenAI-compatible API surface
- privacy tiers enforced by scheduling policy

Out of scope for V1:

- arbitrary customer code on provider machines
- token, ICO, or speculative settlement model
- generic VM marketplace
- full Kubernetes-like workload platform
- unrestricted container execution on consumer PCs
- claims of guaranteed income or investment return

## 3. Core Hypotheses

H1: Heterogeneous GPUs can execute a model together automatically when model manifests, hardware profiles, and topology measurements are accurate enough.

H2: Real internet links can support at least one useful inference mode: interactive regional pipeline inference, MoE/expert routing, or batch inference.

H3: Adaptive verification can provide acceptable trust without destroying unit economics through full duplicate execution.

H4: A consumer-grade provider node can be safe, comprehensible, and low-maintenance enough for non-specialist users.

H5: An OpenAI-compatible API can make developer adoption practical while ComputeMesh-specific controls remain available as extensions.

## 4. Go/No-Go Gates

### Gate 1: Technical Execution

Question: Can heterogeneous GPUs automatically execute one model together?

Evidence required:

- at least two GPU classes participate in one inference path
- model placement is generated automatically from manifests and profiles
- first token and subsequent tokens are produced without manual shard scripting
- metrics identify compute time, transfer time, queue time, and memory pressure

Decision:

- pass: continue to heterogeneous and internet tests
- fail: redesign partitioning/runtime integration before marketplace work

### Gate 2: Internet Performance

Question: Is inference usable over real network links?

Evidence required:

- WAN tests across at least two physical sites
- TTFT, tokens/sec, traffic/token, jitter sensitivity, and recovery time recorded
- comparison of QUIC and gRPC data-plane behavior
- at least one viable execution mode identified

Decision:

- pass interactive: prioritize user-facing distributed inference
- pass regional only: focus on regional clusters and topology density
- pass batch/MoE only: reposition around batch or expert routing
- fail: pause productization and continue research

### Gate 3: Unit Economics

Question: Is cost/token credible after compute, network, verification, payment, reserves, and platform margin?

Evidence required:

- per-job ledger model
- provider payout simulation
- verification cost model
- network traffic cost model
- comparison to GPU cloud and hosted inference alternatives

Decision:

- pass: proceed toward marketplace alpha
- fail: narrow to high-value workloads, private clusters, or enterprise/SLA routing

## 5. Target Architecture

ComputeMesh is split into control plane and data plane.

Control plane:

- identity and node enrollment
- hardware profiles and benchmarks
- model registry and shard manifests
- topology graph and network metrics
- scheduler and placement planner
- job orchestration and state machines
- verification, reputation, billing, and telemetry

Data plane:

- shard transfer and cache management
- activation and KV-cache transport
- runtime worker execution
- result streaming
- verification traces and canary payloads
- failover route updates

The control plane optimizes the plan. The data plane executes the plan with minimal overhead.

## 6. Workstreams

### WS1: Research and Architecture

Purpose: reduce unknowns before building marketplace features.

Deliverables:

- `ARCHITECTURE.md` v0.1
- `PROTOCOL.md` v0.1
- first ADRs for runtime, transport, scheduler, and model manifest
- comparative notes for Petals, exo, llama.cpp, vLLM, DeepSpeed, Ray, NCCL, gRPC, and QUIC
- benchmark metric definitions

Acceptance criteria:

- every major technical bet has an owner, a measurement plan, and an ADR
- M1 lab architecture is reproducible from documentation

### WS2: Node and Hardware Profiling

Purpose: make provider machines observable and schedulable.

Deliverables:

- Windows-first node daemon design
- hardware discovery for CPU, RAM, GPU, VRAM, CUDA/ROCm/Metal capability, driver, OS, storage, network, power, and temperature
- benchmark harness for GEMM, attention, KV-cache, memory bandwidth, quantized GEMM, prefill, decode, embedding, and network transfer
- dynamic hardware profile schema

Acceptance criteria:

- node profile updates are versioned and timestamped
- performance variance is captured over time
- scheduler can reject unsuitable nodes using profile data

### WS3: Model Registry and Sharding

Purpose: make models machine-readable, reproducible, and placeable.

Deliverables:

- model manifest schema
- shard manifest schema with hashes, signatures, quantization, architecture, layer ranges, expert ranges, and backend compatibility
- content-addressed shard reference format
- local shard cache design
- registry API draft

Acceptance criteria:

- a model can be described without manual runtime assumptions
- the scheduler can infer memory needs, legal partitioning strategies, and backend constraints
- shards are immutable and auditable

### WS4: Runtime and Data Plane

Purpose: prove remote model execution with reliable measurement.

Deliverables:

- remote shard loading prototype
- token pipeline prototype
- activation/KV transfer protocol experiment
- QUIC/gRPC comparison
- metrics around TTFT, tokens/sec, traffic/token, GPU utilization, pipeline bubbles, memory pressure, and retry time

Acceptance criteria:

- two GPUs produce a shared inference result
- instrumentation is good enough to explain bottlenecks
- failures produce deterministic error states or retries

### WS5: Scheduler and Topology Engine

Purpose: turn heterogeneous hardware into a usable execution plan.

Initial score:

```text
score = (compute * reliability * locality * availability) / (latency * price * failure_risk)
```

Deliverables:

- topology graph model
- network class classifier
- placement planner for pipeline parallelism and expert parallelism
- initial multi-objective optimizer design
- replanning logic for node failure

Acceptance criteria:

- planner selects nodes from dynamic profiles
- planner explains why a placement was chosen
- planner avoids WAN strategies that require datacenter-grade interconnect

### WS6: Verification and Reputation

Purpose: reduce dishonest or faulty results without full duplicate execution by default.

Deliverables:

- verification levels 0-4 design
- canary jobs
- random redundancy
- challenge/response interface
- reputation schema
- risk-based verification rate policy

Acceptance criteria:

- new nodes receive higher verification rates
- trusted nodes can graduate to lower sampling rates
- high-value jobs can require stronger verification
- verification outcomes affect scheduling and payout

### WS7: Billing and Ledger

Purpose: close a real economic loop without token complexity.

Deliverables:

- fiat billing model
- internal high-resolution ledger schema
- job cost breakdown for compute, network, verification, reserve, and platform fee
- provider balance accounting
- refund/retry semantics

Acceptance criteria:

- every completed job has an auditable cost trail
- failed or retried jobs do not create false billing
- payout calculations are deterministic and reproducible

### WS8: UX and Developer API

Purpose: make the system usable by consumers, providers, and developers.

Deliverables:

- Windows node UI concept
- provider controls for availability, power limit, privacy tier, minimum price, and stop-sharing
- "Run Massive Model" consumer flow
- OpenAI-compatible endpoints:
  - `/v1/chat/completions`
  - `/v1/responses`
  - `/v1/embeddings`
  - `/v1/models`
- ComputeMesh extensions for privacy tier, deadline, budget, quality target, and preferred regions

Acceptance criteria:

- user is not exposed to manual CUDA setup, port forwarding, or shard placement
- node status, earnings, GPU usage, temperature, and error states are obvious
- API compatibility is sufficient for existing client libraries to test simple workloads

### WS9: Security, Privacy, and Compliance

Purpose: protect providers, users, and the project before public exposure.

Deliverables:

- `THREAT_MODEL.md`
- signed worker/update model
- privacy tier policy
- no arbitrary code execution policy for V1
- supply-chain verification plan
- security disclosure process
- legal review checklist for privacy, payments, trademarks, and IP

Acceptance criteria:

- provider node cannot run untrusted user shell/Python/container workloads
- privacy tiers are enforceable scheduler constraints
- release artifacts can be signed and rolled back

### WS10: Launch and Growth

Purpose: launch only after technical proof and safety foundations exist.

Deliverables:

- private alpha readiness checklist
- provider onboarding checklist
- public alpha readiness checklist
- launch metrics dashboard
- incident response process
- positioning by validated execution mode

Acceptance criteria:

- public claims match measured evidence
- no yield or return promises are made
- support, status, diagnostics, and rollback paths exist

## 7. Ninety-Day Execution Plan

### Days 1-14: M0 Research and Architecture

Primary goal: build the technical foundation and measurement harness.

Deliverables:

- repository structure
- ADR template and first ADRs
- benchmark harness specification
- two-node lab plan
- model manifest draft
- transport evaluation plan
- first threat model

Key tasks:

- analyze Petals, exo, llama.cpp, vLLM, DeepSpeed, Ray, and NCCL
- define benchmark cases for prefill, decode, KV-cache, network transfer, and recovery
- choose initial dense-model and MoE test targets
- define node profile schema
- define job and node state machines
- build reproducible lab checklist

Exit criteria:

- M1 can start without architectural ambiguity
- all M1 success metrics are measurable

### Days 15-35: M1 Two GPUs

Primary goal: two computers jointly execute a model that does not fit on the smaller node.

Deliverables:

- remote shard load prototype
- token pipeline prototype
- basic scheduler placement for two known nodes
- structured metrics output

Key tasks:

- register two nodes with hardware profiles
- load local and remote shard segments
- stream activations or intermediate outputs
- produce first shared token
- record TTFT, tokens/sec, traffic/token, and GPU utilization

Exit criteria:

- Gate 1 evidence exists
- limitations and bottlenecks are documented

### Days 36-56: M2 Heterogeneous Cluster

Primary goal: automatic partitioning across multiple different GPU sizes.

Deliverables:

- planner for 8 GB + 8 GB + 16 GB + 24 GB class setup
- memory-aware partitioning
- profile-based node selection
- basic failure-aware job planning

Key tasks:

- add dynamic hardware profile updates
- implement placement explanations
- measure GPU idle time and pipeline bubbles
- test slow-node sensitivity
- compare manual and automatic placement

Exit criteria:

- model placement is generated automatically
- heterogeneous performance characteristics are visible in metrics

### Days 57-70: M3 Real Internet

Primary goal: understand whether WAN inference is interactive, regional, batch-oriented, or MoE-first.

Deliverables:

- WAN test plan and results
- QUIC/gRPC comparison
- latency model
- traffic/token report
- revised scheduler policy

Key tasks:

- run nodes in different physical locations
- inject latency, jitter, and packet loss
- compare pipeline depth and shard sizes
- measure recovery from transient disconnects
- evaluate regional grouping

Exit criteria:

- Gate 2 decision is made using measured data
- next architecture direction is explicit

### Days 71-80: M4 70B Demonstrator

Primary goal: show a user with 8 GB VRAM starting a model larger than local capacity.

Deliverables:

- 70B-class demo path
- user-facing demo script
- model-ready flow prototype
- performance report

Key tasks:

- prepare model manifest and shards
- automate compute discovery
- stream visible model readiness progress
- measure user-perceived latency
- document hardware and network conditions

Exit criteria:

- a non-local model runs through ComputeMesh
- demo is reproducible on documented machines

### Days 81-90: M5 Failover

Primary goal: survive or cleanly retry when a node disappears during inference.

Deliverables:

- replica or replan prototype
- failure injection test
- retry/refund semantics
- demo recording plan

Key tasks:

- remove a node during active chat
- detect failure quickly
- re-route affected stage or fail cleanly
- preserve billing correctness
- report recovery time

Exit criteria:

- node failure does not produce silent corruption
- user receives either a correct answer or a clean retry
- billing remains accurate

## 8. Data Model

Core entities:

- `users`
- `nodes`
- `hardware`
- `benchmarks`
- `models`
- `model_shards`
- `jobs`
- `job_segments`
- `payments`
- `ledger`
- `reputation`
- `verification`
- `sessions`
- `clusters`
- `network_metrics`

Design principles:

- every state transition is idempotent
- every job is auditable from model version to payout
- scheduler inputs are versioned
- verification outcomes are immutable
- ledger entries are append-only

## 9. State Machines

Node states:

```text
OFFLINE -> CONNECTING -> AUTHENTICATING -> BENCHMARKING -> READY
READY -> ASSIGNED -> LOADING -> SERVING -> DRAINING -> READY
ERROR STATES: FAILED, QUARANTINED, BANNED
```

Job states:

```text
CREATED -> PLANNING -> RESERVING -> DISPATCHING -> RUNNING -> VERIFYING -> COMPLETED -> SETTLED
RECOVERY STATES: RETRY, REPLAN, FAILED, REFUNDED
```

All transitions must be:

- idempotent
- logged
- recoverable after crash
- tied to actor identity
- safe under retry

## 10. Metrics and KPIs

Technical KPIs:

- TTFT
- tokens/sec
- effective VRAM
- traffic/token
- GPU utilization
- pipeline bubble ratio
- jitter sensitivity
- recovery time
- verification pass rate
- abort rate

Economic KPIs:

- cost/token
- provider payout/token
- platform margin
- verification overhead
- network overhead
- refund rate
- paid workload retention

Operational KPIs:

- node availability
- install success rate
- benchmark completion rate
- crash rate
- update rollback rate
- support tickets per active node

## 11. Testing Strategy

Test layers:

- unit tests for scheduler, ledger, manifests, verification, and state machines
- integration tests for node, scheduler, registry, gateway, and runtime
- distributed tests across heterogeneous devices
- chaos tests with node failure, network loss, high latency, packet loss, corrupted shard, scheduler restart, and database failover
- performance tests for TTFT, tokens/sec, traffic/token, GPU utilization, and recovery
- security tests for signed workers, update path, API auth, and supply chain
- billing tests for rounding, retries, refunds, duplicate events, and settlement

Definition of success:

- failures are expected and observable
- silent corruption is unacceptable
- billing neutrality is preserved during retries
- every performance claim maps to measured data

## 12. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| WAN latency makes dense pipeline inference unusable | Product positioning risk | Test early; pivot to regional clusters, batch, or MoE |
| Consumer nodes are unreliable | Session failures | Replication, predictive availability, fast replan |
| Verification costs destroy margins | Economic failure | Adaptive sampling and high-risk duplication only |
| Provider host security is weak | Trust failure | V1 signed workers only, no arbitrary code |
| CUDA/runtime complexity slows progress | Delivery risk | Start with narrow model/runtime target |
| Payment compliance delays launch | Launch risk | Fiat ledger first, legal review before public alpha |
| Trademark/IP uncertainty | Public release risk | Perform prior-art, trademark, and license review before broad publication |
| User setup is too hard | Adoption risk | Windows-first installer, diagnostics, auto-update |

## 13. Launch Readiness

Do not launch publicly until:

- installer is signed and reproducible
- auto-update supports rollback
- GPU and driver checks are robust
- node cannot destabilize the host
- power and temperature limits work
- privacy tiers are technically enforced
- payment and ledger tests pass
- canary and verification systems are active
- crash reporting is data-minimizing
- public status page exists
- minimum hardware is documented
- earnings and costs are clearly shown
- no return promises are made
- support and incident response exist
- `SECURITY.md` is live
- brand, domain, privacy, terms, and payment model are legally reviewed

## 14. Immediate Next Actions

1. Create ADR template and M0 ADRs.
2. Select the first runtime target and first model target.
3. Build the benchmark harness specification.
4. Prepare the two-node lab.
5. Implement node profile schema.
6. Prototype model manifest and shard manifest.
7. Decide QUIC/gRPC experiment design.
8. Define exact Gate 1 measurements.
9. Start security review for signed worker and update model.
10. Keep `state.md` current after every meaningful change.
