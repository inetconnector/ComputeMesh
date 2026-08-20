# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Project stage:** M0 — contracts, benchmarking, architecture, protocol, security, and feasibility research.  
> **Implementation status:** the first executable M0 engineering tooling now exists; no production runtime, marketplace, scheduler, billing system, or public provider-node software exists yet.

ComputeMesh is an experimental distributed AI inference system intended to make heterogeneous compute resources usable as one logical execution fabric. A client with limited local VRAM should eventually be able to run a model whose memory and compute requirements exceed the client machine by using approved remote compute without manually managing shards, hosts, ports, or placement.

**North Star:** the user chooses a model and a policy; ComputeMesh determines feasibility, selects compatible capacity, prepares verified model partitions, executes inference, handles failures, verifies results according to risk, and produces an auditable cost record.

“The internet is your GPU” is a product metaphor, not a performance guarantee. WAN latency, bandwidth, jitter, hardware heterogeneity, provider trust, model licensing, and failure probability are first-class constraints.

## Current status

### Implemented

- bilingual root documentation and ADR process;
- architecture, protocol, security, benchmark, failure, privacy, and data-model specifications;
- JSON Schema Draft 2020-12 contracts for:
  - node profile;
  - benchmark result;
  - model manifest;
  - shard manifest;
  - reservation;
  - job;
- concrete example manifests/jobs/reservations;
- a standard-library Python M0 benchmark collector that records host inventory and NVIDIA GPU/VRAM/driver information when `nvidia-smi` is available;
- unit tests for the benchmark collector.

### Not implemented

- production provider node agent;
- runtime worker or distributed inference execution;
- gateway/API;
- scheduler/orchestrator;
- model registry service;
- verification/reputation service;
- billing/ledger service;
- telemetry service;
- desktop/dashboard applications;
- production deployment/update pipeline;
- public release.

The canonical handoff is `state.md`.

## Engineering invariants

1. **No arbitrary customer code on provider nodes in V1.**
2. **Hard scheduling constraints are evaluated before optimization.**
3. **No job is billed for work the platform cannot attribute and audit.**
4. **Retries, replays, timeouts, and duplicate events must not create duplicate business effects.**
5. **Provider nodes are assumed to fail, disconnect, lie, or be compromised.**
6. **Public compute does not imply prompt confidentiality.**
7. **Performance claims require reproducible measurements and test conditions.**
8. **The data plane carries only approved inference-protocol data.**
9. **Model artifacts are immutable, content-addressed, versioned, and verified before execution.**
10. **The system must explain why a placement was accepted or rejected.**

Changes to these invariants require an ADR.

## Architecture at a glance

```text
Client / SDK
    |
    v
Gateway / API
    |
    v
Job Orchestrator
    |
    +------> Scheduler + Topology
    +------> Registry
    +------> Policy / Verification
    |
    v
Capacity reservations
    |
    v
Provider execution mesh
Node A <---- activation/result streams ----> Node B
    |
    v
Telemetry / Metering / Ledger
```

For dense pipeline execution, normal inter-node token traffic is expected to be stage activations/results. KV cache normally remains with the layers that own it; KV movement is primarily a migration, recovery, or rebalancing concern.

## Feasibility gates

| Gate | Question | Minimum evidence |
| --- | --- | --- |
| G0 | Is M1 defined well enough to implement? | accepted required ADRs, schemas, lab definition, testable DoD |
| G1 | Can heterogeneous devices execute one model path automatically? | automatic placement, correct shared inference, measured timings |
| G2 | Which modes remain usable over real networks? | LAN/WAN TTFT, decode, traffic, jitter/loss/recovery |
| G3 | Is cost/token credible? | measured execution + verification/network/payment economics |
| G4 | Can untrusted capacity be used safely enough? | workload boundary, identity, auditability, verification, abuse controls |
| G5 | Can non-specialists operate provider nodes? | install/update/rollback/diagnostics/drain/uninstall |

A failed gate may change the viable workload class rather than end the project.

## Repository map

```text
ComputeMesh/
├─ apps/                 # planned node/desktop/dashboard/admin surfaces
├─ services/             # planned gateway/scheduler/registry/billing/verification/telemetry
├─ runtime/              # planned CUDA/llama.cpp/vLLM/network integrations
├─ protocol/
│  ├─ schemas/           # machine-readable M0 contracts
│  └─ examples/          # contract examples
├─ tools/
│  └─ benchmark/         # first executable M0 collector + unit tests
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

## Run the first M0 tool

Python 3.10+ is sufficient for the current collector; it has no third-party runtime dependency.

```powershell
git clone <repository-url>
cd ComputeMesh
python tools/benchmark/benchmark.py --dry-run
python -m unittest discover -s tools/benchmark/tests -v
```

To write a lab profile:

```powershell
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

Output is written below `artifacts/benchmark/` and ignored by Git.

The collector currently records OS/architecture, Python version, CPU/logical cores, physical memory, and NVIDIA GPU name/VRAM/driver when available. It deliberately does not collect hostnames, GPU UUIDs, prompts, outputs, or other unnecessary identifiers.

## Documentation order

1. `state.md` — current facts, blockers, and next actions.
2. `IMPLEMENTATION_PLAN.md` — gates, milestones, workstreams, and definitions of done.
3. `ARCHITECTURE.md` — service boundaries and execution/scheduling model.
4. `PROTOCOL.md` — control/data-plane semantics, retries, errors, leases, cancellation.
5. `THREAT_MODEL.md` and `SECURITY.md` — trust assumptions and launch blockers.
6. `docs/BENCHMARK_SPEC.md` — reproducible measurement rules.
7. `docs/DATA_MODEL.md` and `docs/FAILURE_SEMANTICS.md` — canonical entities/state behavior.
8. `protocol/schemas/` — current machine-readable M0 contracts.
9. `docs/adr/` — accepted/proposed architecture decisions.

## Runtime direction

The first proposed M1 research path is llama.cpp-oriented, wrapped behind the ComputeMesh node/worker boundary. vLLM remains a comparison/reference for coordinated datacenter-style serving. ADR 0002 is still **Proposed**, not accepted; the runtime choice is accepted only after a two-node spike proves deterministic placement, measurable transfer, correctness, bounded memory, cancellation/failure behavior, and a workable Windows path.

Control and data transports are also still under evaluation. Transport encryption must never be confused with confidential execution on a provider-controlled host.

## Immediate engineering sequence

```text
machine-readable contracts + inventory harness   [started]
-> two-node lab profiles
-> runtime spike
-> reservation/job state skeleton
-> activation transport benchmark
-> shared two-node inference
-> scheduler automation
-> failure/replan tests
```

The scheduler should be driven by measured node/runtime/network behavior rather than static GPU-name tables.

## Security warning

Do not expose experimental runtime RPC endpoints directly to the public internet. Third-party runtimes are implementation details behind ComputeMesh authentication, authorization, workload restrictions, rate limits, artifact verification, and network policy.

`confidential_compute` is not a valid guarantee until a concrete trusted-execution and attestation design exists.

## Language synchronization rule

Root documentation is permanently maintained in two synchronized files:

- `README.md` — English;
- `README.de.md` — German.

Any public-facing change to project status, product boundaries, architecture overview, setup, roadmap, or security warnings must update both files in the same change.

## License

The project remains all-rights-reserved until the owner selects and publishes an explicit license. Repository visibility does not grant open-source rights.
