# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Stage:** M0 foundation moving into the first controlled M1 shared-runtime experiment.  
> **Important:** ComputeMesh is **not yet a production distributed-inference product**. The Windows/Linux setup prepares the lab/benchmark workflow that actually exists today; it is not a public provider-node installer.

ComputeMesh explores whether heterogeneous computers can cooperate as one model-aware AI inference fabric. The long-term goal is simple: choose a model and policy, while ComputeMesh handles feasibility, placement, preparation, execution, failures, verification, and auditable accounting.

## Fastest way to try the lab tooling

Clone/download the repository and use the launcher for your OS:

**Windows:** double-click `SETUP.cmd`  
**Linux:** run `./setup.sh` (or `bash setup.sh` if the executable bit was lost).

Both launchers expose the same simple menu for profile capture, trusted-LAN RTT/throughput measurement, local llama.cpp benchmarking, and the current complete local test set. Model weights are never downloaded automatically.

The detailed two-computer walkthrough is in [setup/README.md](setup/README.md).

## Current implementation

Implemented foundations now include:

- cross-platform Windows/Linux Lab Setup;
- inventory, TCP network, and llama.cpp `llama-bench` measurement tooling;
- Draft-2020-12 machine-readable state/control contracts;
- deterministic Job/Reservation semantics and transactional SQLite reference persistence;
- strict transport-neutral control envelopes and durable initial handlers;
- authentication-gated node-session semantics and strict initial wire binding;
- M1 reference node identity `computemesh-ed25519-v1` with enrollment/key-rotation/revocation reference state;
- a controlled llama.cpp RPC **research harness** for the first M1 shared-runtime experiment;
- a loopback-only TCP **measurement relay** for opaque RPC byte accounting, deterministic userspace delay/jitter, and controlled disconnect experiments;
- a deterministic M1 **two-node placement planner** that generates explainable local/shared feasibility candidates from current profiles, model manifest, llama-bench evidence and network measurements without inventing distributed-performance numbers.

## M1 two-node placement planner

`services/scheduler/placement.py` is the first machine-readable placement component. It is an **experiment feasibility planner**, not a production scheduler.

It checks:

- node/profile schemas and exact profile revisions;
- draining and stale/future-skewed profiles;
- selected model artifact size against all four llama-bench records;
- `contiguous_layers` permission in the model manifest;
- provider memory fractions plus a conservative planner memory cap;
- a required coordinator→worker network measurement and caller-asserted peer node ID.

It can emit:

- `shared_experiment` when a conservative contiguous two-node layer split is memory-feasible;
- `local_only` when only the coordinator baseline is feasible;
- `no_plan` when current hard constraints/memory evidence allow neither.

The output includes deterministic `decision_id`, contiguous layer ranges, relative `tensor_split` weights, hard-constraint explanations and the measured individual compute/network evidence.

Critically, before a correct measured shared-runtime run exists it always leaves:

```text
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

The current benchmark-result v1 does not structurally encode the network target node, so the planner labels that binding `caller_asserted_v1` instead of pretending it is stronger evidence. The model layer count is also an explicit experiment input because model-manifest v1 does not carry it yet. See [services/scheduler/README.md](services/scheduler/README.md).

## Controlled llama.cpp M1 experiment

`runtime/llama/rpc_spike.py` can discover current llama.cpp devices, record a deterministic local baseline, run an explicit local+RPC `layer` split, and compare the exact same model/prompt by token-ID digest when available (otherwise output digest). It records model/runtime/topology/timing evidence without raw prompt/output persistence.

The first experiment keeps coordinator HTTP on `127.0.0.1`, restricts RPC to literal loopback/RFC1918 IPv4, uses `--offline`, disables automatic fitting and cache surfaces, and treats upstream RPC only as a trusted-lab implementation detail. See [runtime/llama/README.md](runtime/llama/README.md).

**ADR 0002 remains Proposed.** The harness and planner prepare the proof; no real correct shared two-node inference result has been recorded yet.

## Runtime network measurement relay

`runtime/network/tcp_relay.py` can sit locally between the llama coordinator and a trusted-private-LAN RPC worker. It listens only on `127.0.0.1`, connects only to literal loopback/RFC1918 IPv4, uses bounded queues, counts opaque bytes separately in both directions, separates setup/active timing, can add reproducible userspace stream delay/jitter, and can force controlled disconnects.

The relay does not parse RPC frames: byte totals include framing/control/data and are **not activation-tensor byte counts**. It also deliberately does not emulate packet loss by dropping TCP bytes. Packet-level loss/reordering remains a separate OS/network-emulation experiment. See [runtime/network/README.md](runtime/network/README.md).

## Verified real-target evidence

Existing physical-target evidence from 2026-08-21 includes:

- Windows target: RTX 3080 Laptop GPU, 16 GiB VRAM, 31.7 GiB RAM;
- Linux target: Debian 13 server, 4 logical CPU cores, 7.8 GiB RAM, CPU-only;
- Windows → internet Linux engineering TCP measurement: RTT p50 `11.884 ms`, p95 `13.369 ms`, upload p50 `42.276 Mbit/s`, download p50 `226.597 Mbit/s`;
- Windows CUDA llama.cpp 7B-Q4 benchmark: prefill `2866.127 tok/s`, decode `76.210 tok/s`;
- Linux CPU llama.cpp 0.5B-Q4 smoke: prefill `12.382 tok/s`, decode `0.201 tok/s`.

The internet network result is not a trusted-private-LAN A/B proof and is not distributed shared inference. The relay and placement planner currently have cross-platform software evidence, not real two-machine shared-runtime evidence.

## Identity and runtime security boundary

ADR 0005 is accepted **only for the narrow M1 reference implementation**. Missing before public network exposure include provider/user authentication around identity APIs, OS-protected node private-key storage, active-session revocation fan-out, authenticated/encrypted transport, authorization/rate/resource limits, and production service/database operation.

Upstream llama.cpp RPC remains **trusted-lab-only**. Current ComputeMesh identity/session authentication does not authenticate the upstream RPC socket; neither the local relay nor the feasibility planner changes that. Never expose the RPC worker to the public internet or an untrusted network.

`confidential_compute` is not a valid guarantee until a concrete trusted-execution/attestation design exists.

## Not implemented yet

There is still no production provider-node installer/service, no completed distributed shared-inference result, no calibrated/production scheduler ranking, no production Gateway/API, no production identity network service, no complete artifact/runtime/failure wire path, no production runtime transport, no packet-level loss/reordering experiment, no billing/verification/telemetry product stack, and no signed production release/update pipeline.

## Immediate path

```text
profiles + local benchmarks + trusted-LAN path evidence
        ↓
machine-readable conservative placement candidate
        ↓
local deterministic llama-server baseline
        ↓
explicit local + RPC layer split
        ↓
correctness + timing comparison
        ↓
opaque RPC byte accounting + delay/jitter/disconnect experiments
        ↓
first reproducible correct shared two-node inference
        ↓
calibrate placement prediction/ranking from measured shared evidence
        ↓
packet-level loss/reordering experiment where material
```

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # simple Windows/Linux lab entry points
├─ setup/                 # cross-platform lab orchestration
├─ tools/benchmark/       # inventory, TCP, llama-bench adapters
├─ services/orchestrator/ # durable M0 state/control foundation
├─ services/identity/     # M1 reference enrollment/key registry
├─ services/scheduler/    # deterministic M1 two-node feasibility planner
├─ protocol/              # contracts, session wire binding, Ed25519 verifier
├─ runtime/llama/         # controlled llama.cpp M1 research spike
├─ runtime/network/       # bounded M1 TCP measurement relay
├─ docs/                  # specifications and ADRs
└─ state.md               # canonical engineering handoff
```

For engineering details, read `state.md` first, then `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md`, and the ADRs.

## Language synchronization rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.
