# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Project stage:** M0 — architecture, protocol, security, benchmarking, and feasibility research.  
> **Production status:** no production runtime, marketplace, scheduler, billing system, or public node software exists yet.

ComputeMesh is an experimental distributed AI inference system intended to make heterogeneous compute resources usable as one logical execution fabric. The core product thesis is that a client with limited local VRAM should be able to run a model whose memory and compute requirements exceed the client machine by using trusted remote compute without manually managing shards, hosts, ports, or placement.

**North Star:** the user chooses a model and a policy; ComputeMesh determines whether the request is feasible, selects compatible capacity, prepares model partitions, executes inference, handles failures, verifies results according to risk, and produces an auditable cost record.

The phrase **“The internet is your GPU”** is a product metaphor, not a claim that arbitrary internet-connected GPUs can be coupled with datacenter-like efficiency. Network latency, bandwidth, jitter, hardware heterogeneity, provider trust, model licensing, and failure probability are first-class constraints.

## What ComputeMesh is

ComputeMesh is designed as a **model-aware distributed inference fabric** with:

- automatic provider-node enrollment, hardware discovery, and benchmarking;
- signed model and shard manifests;
- topology-aware placement with hard privacy, compatibility, memory, and policy constraints;
- pipeline, expert, data-parallel, and local tensor-parallel execution where appropriate;
- capacity reservation and failure-aware replanning;
- structured telemetry and reproducible benchmark evidence;
- risk-based verification and node reputation;
- auditable fiat-denominated billing and provider settlement;
- a Windows-first provider experience for V1;
- an OpenAI-compatible public API plus ComputeMesh-specific policy controls.

## What ComputeMesh is not

V1 is intentionally **not**:

- a generic VM or container marketplace;
- a platform for arbitrary customer shell, Python, CUDA, or container execution on provider PCs;
- a cryptocurrency, ICO, mining, or yield product;
- a claim that WAN tensor parallelism is practical;
- a promise that prompts are confidential on untrusted consumer nodes;
- a replacement for high-speed intra-datacenter GPU interconnect;
- a production-ready system today.

## Core engineering invariants

These are stronger than implementation preferences. Changes require an ADR.

1. **No arbitrary customer code on provider nodes in V1.**
2. **Hard scheduling constraints are evaluated before optimization.**
3. **No job is billed for work the platform cannot attribute and audit.**
4. **A retry, replay, timeout, or duplicate event must not create duplicate payout or state advancement.**
5. **Provider nodes are assumed to fail, disconnect, lie, or be compromised.**
6. **Public-compute nodes do not imply prompt confidentiality.**
7. **Performance claims require reproducible measurements and test conditions.**
8. **The data plane carries only approved inference protocol data.**
9. **Model artifacts are immutable, content-addressed, versioned, and verified before execution.**
10. **The system must be able to explain why a placement was accepted or rejected.**

## Architecture at a glance

```text
                         +-----------------------+
 Client / SDK ---------->| Gateway / API         |
                         +-----------+-----------+
                                     |
                                     v
                         +-----------------------+
                         | Job Orchestrator      |
                         +-----------+-----------+
                                     |
                  +------------------+------------------+
                  |                  |                  |
                  v                  v                  v
          +---------------+  +---------------+  +----------------+
          | Scheduler     |  | Registry      |  | Policy/Trust   |
          | + topology    |  | models/shards |  | verification   |
          +-------+-------+  +-------+-------+  +--------+-------+
                  |                  |                   |
                  +------------------+-------------------+
                                     |
                              reservations
                                     |
                                     v
             +---------------- Provider execution mesh ----------------+
             |                                                          |
             |  Node A  <---- activation/result streams ---->  Node B   |
             |    |                                             |       |
             | local layers/KV                              local layers/KV|
             |                                                          |
             +----------------------------------------------------------+
                                     |
                                     v
                         +-----------------------+
                         | Telemetry + Ledger    |
                         +-----------------------+
```

### Control plane

The control plane owns identity, enrollment, policy, topology, model metadata, scheduling, reservations, job state, verification policy, telemetry aggregation, and billing records.

### Data plane

The data plane executes an already-approved plan. For a dense pipeline path, the normal per-token inter-node traffic is primarily **activation data between stages**, not continuous transfer of all KV cache. KV state should normally remain co-located with the layers that own it; KV migration is a recovery, migration, or rebalancing operation.

### Provider node

A provider node exposes constrained inference capacity, not a remote general-purpose machine. It reports capabilities and availability, accepts signed assignments, prepares verified model artifacts, executes approved stages, emits bounded telemetry, and can drain safely.

## Feasibility gates

ComputeMesh is research-driven. Product work expands only after evidence exists.

| Gate | Question | Minimum evidence |
| --- | --- | --- |
| G1 — Execution | Can heterogeneous devices automatically execute one model path? | automatic placement, shared inference result, measurable compute/transfer/queue timings |
| G2 — Network | Which distributed modes remain usable over real links? | LAN/WAN measurements for TTFT, decode rate, traffic/token, jitter, loss, recovery |
| G3 — Economics | Is cost/token credible after all overhead? | provider cost model, verification overhead, network cost, reserve, platform margin |
| G4 — Trust | Can untrusted capacity be used without unacceptable security/correctness risk? | signed workload boundary, identity, auditability, verification evidence, abuse controls |
| G5 — Operability | Can non-specialist providers run nodes safely? | installer/update/rollback, diagnostics, thermal limits, clean drain, supportability |

A failed gate is not automatically a failed project. It may change positioning from global interactive dense inference toward regional clusters, batch work, dedicated providers, or MoE/expert-oriented research.

## Repository map

```text
ComputeMesh/
├─ apps/
│  ├─ node/          # provider daemon/local UX
│  ├─ desktop/       # end-user desktop UX
│  ├─ dashboard/     # web UX
│  └─ admin/         # operations UX
├─ services/
│  ├─ gateway/
│  ├─ scheduler/
│  ├─ registry/
│  ├─ billing/
│  ├─ verification/
│  └─ telemetry/
├─ runtime/
│  ├─ cuda/
│  ├─ llama/
│  ├─ vllm/
│  └─ network/
├─ protocol/
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/
   ├─ adr/
   ├─ BENCHMARK_SPEC.md
   ├─ DATA_MODEL.md
   ├─ FAILURE_SEMANTICS.md
   ├─ PRIVACY_TIERS.md
   └─ TEST_MATRIX.md
```

## Documentation map

Start here:

1. `README.md` / `README.de.md` — project boundaries and current status in English and German.
2. `IMPLEMENTATION_PLAN.md` — milestones, dependencies, gates, and definitions of done.
3. `ARCHITECTURE.md` — system boundaries, flows, consistency model, and scheduling model.
4. `PROTOCOL.md` — protocol envelope, control messages, transport semantics, errors, retries, and compatibility.
5. `THREAT_MODEL.md` — assets, actors, trust boundaries, threats, mitigations, and residual risk.
6. `docs/BENCHMARK_SPEC.md` — reproducible measurements required before scheduler decisions.
7. `docs/DATA_MODEL.md` — canonical entities and invariants.
8. `docs/FAILURE_SEMANTICS.md` — state transitions, leases, retries, replanning, and billing neutrality.
9. `docs/PRIVACY_TIERS.md` — what each privacy tier guarantees and explicitly does not guarantee.
10. `state.md` — current facts, decisions, blockers, and next actions.

## Planned technology direction

These are **candidates**, not frozen choices:

- **Go** — control-plane services and node daemon;
- **C++/CUDA** — performance-critical runtime integration;
- **Python** — ML systems research and benchmark tooling;
- **TypeScript/React** — desktop/web interfaces;
- **PostgreSQL** — durable control-plane and ledger state;
- **gRPC/HTTP2 and QUIC-based transports** — experiment candidates for control/data-plane needs;
- **llama.cpp and vLLM** — reference runtime integrations to evaluate rather than blindly wrap.

An ADR must record each choice before it becomes a project dependency.

## Current reality

Implemented:

- repository structure;
- architecture, protocol, security, and implementation planning;
- ADR process;
- documentation bootstrap.

Not implemented:

- executable node;
- gateway/API;
- scheduler;
- model registry;
- distributed runtime;
- verification service;
- billing ledger;
- telemetry service;
- desktop/dashboard apps;
- deployment;
- automated tests.

## Development setup

There is no application to build yet. At M0, setup is documentation and research oriented.

```powershell
git clone <repository-url>
cd ComputeMesh
Get-Content README.md
Get-Content state.md
Get-Content IMPLEMENTATION_PLAN.md
```

When code is introduced, exact toolchain versions must be pinned in a reproducible bootstrap script and CI image rather than maintained only as prose.

## Security warning

Do not expose experimental runtime RPC endpoints directly to the public internet. Any third-party runtime integration must be treated according to its own security posture and wrapped behind ComputeMesh authentication, authorization, workload restrictions, rate limits, and network policy before provider use.

See `SECURITY.md` and `THREAT_MODEL.md`.

## Language and synchronization rule

The root documentation is maintained bilingually:

- `README.md` — English;
- `README.de.md` — German.

Both files must be updated **in the same change** whenever project status, product boundaries, architecture overview, setup, roadmap, security warnings, or other public-facing information changes. Neither README may be allowed to drift behind the other.

## License

The project remains all-rights-reserved until the owner selects and publishes an explicit license. Do not infer open-source rights from repository visibility or source availability.
