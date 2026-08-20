# ComputeMesh

ComputeMesh is a planned distributed AI execution layer that turns heterogeneous GPUs into a virtual AI machine. The product thesis is simple: a user with a small local GPU should be able to run models that require far more memory and compute by connecting to trusted network resources.

> The internet is your GPU.

This repository is the initial implementation workspace created from `ComputeMesh_Blueprint_v1.0.pdf`. It currently contains the professional execution plan, architecture notes, protocol outline, security posture, and the repository structure needed to start engineering work.

## What ComputeMesh Is

ComputeMesh is not a generic GPU-hours marketplace, a token project, a Kubernetes frontend, or an Ollama clone. It is intended to become a model-aware distributed inference system with:

- automatic node discovery, benchmarking, and hardware profiling
- model manifests, sharding, and content-addressed shard references
- topology-aware scheduling across LAN, regional, and global networks
- support for pipeline, expert, tensor-local, and data parallel execution strategies
- adaptive verification, reputation, and auditable billing
- a Windows-first provider node experience
- an OpenAI-compatible developer API
- a long-term path toward internet-native Mixture-of-Experts research

## Current Repository State

This is a planning and bootstrap repository. No production runtime is implemented yet.

Included now:

- `IMPLEMENTATION_PLAN.md`: detailed execution plan from research through launch readiness
- `ARCHITECTURE.md`: target architecture and component boundaries
- `PROTOCOL.md`: initial protocol and API design outline
- `THREAT_MODEL.md`: initial security and privacy model
- `SECURITY.md`: security policy and disclosure posture
- `CONTRIBUTING.md`: contribution rules for the early project phase
- `state.md`: maintainer and AI handoff document
- service, runtime, app, protocol, model, test, deploy, docs, and research directories

## Repository Layout

```text
computemesh/
  apps/
    node/
    desktop/
    dashboard/
    admin/
  services/
    gateway/
    scheduler/
    registry/
    billing/
    verification/
    telemetry/
  runtime/
    cuda/
    llama/
    vllm/
    network/
  protocol/
  sdk/
  models/
  tests/
  deploy/
  docs/
    adr/
  research/
```

## Implementation Strategy

The first 90 days focus on proof, measurement, and scope control:

1. Establish architecture, protocol, ADRs, and benchmark harness.
2. Prove two GPUs can execute one model together.
3. Add automatic partitioning across heterogeneous GPUs.
4. Test real internet links with QUIC and gRPC comparisons.
5. Demonstrate an 8 GB client using a network model larger than local VRAM.
6. Prove failover or clean retry when a node disappears during inference.

The three primary Go/No-Go gates are:

- heterogeneous GPUs can automatically execute one model together
- real internet performance reaches usable TTFT and tokens/sec for the target workload
- cost/token remains credible after networking, verification, and payment overhead

## Planned Technology Choices

- Go: control plane, scheduler, node daemon, networking, registry, billing
- C++/CUDA: performance-critical runtime integration and kernels
- Python: ML systems research, benchmarks, experiments
- TypeScript/React: desktop and web UI surfaces
- PostgreSQL: durable business, topology, ledger, and audit data
- QUIC/gRPC: data-plane candidates to evaluate in M0 and M3

These choices are provisional until confirmed by ADRs during M0.

## Setup

There is no buildable application yet. To start project work:

```powershell
git clone <repo-url>
cd ComputeMesh
```

Then read:

```powershell
Get-Content README.md
Get-Content state.md
Get-Content IMPLEMENTATION_PLAN.md
```

## Requirements

Early engineering will require:

- Windows test machines with NVIDIA GPUs
- at least one 8 GB VRAM node and one larger GPU node for M1
- CUDA-capable development environment
- stable LAN and WAN test links
- PostgreSQL for later control-plane persistence
- Go, Python, Node.js, and C++/CUDA toolchains once implementation begins

Exact versions will be pinned when the first code modules are introduced.

## Limitations

- No runnable ComputeMesh node exists yet.
- No scheduler, gateway, billing ledger, or verification implementation exists yet.
- The blueprint is a strategic and technical starting point, not proof of feasibility.
- Real internet inference may force a narrower positioning, such as regional clusters, batch execution, or MoE-first expert routing.
- Legal, privacy, payment, trademark, and patent review are required before public launch.

## Contributing

Early contributions should be small, evidence-driven, and tied to `IMPLEMENTATION_PLAN.md`. Architectural changes require ADRs under `docs/adr/`.

See `CONTRIBUTING.md` for branch, commit, test, and review expectations.

## Security

Version 1 must not run arbitrary customer code on provider machines. Only signed ComputeMesh workers and defined inference workloads are in scope.

See `SECURITY.md` and `THREAT_MODEL.md`.

## License

License pending. All rights are reserved until the project owner chooses an explicit open-source or commercial license after IP and legal review.
