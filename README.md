# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Stage:** M0 foundation moving into the first controlled M1 runtime experiment.  
> **Important:** ComputeMesh is **not yet a production distributed-inference product**. The Windows/Linux setup prepares the lab/benchmark workflow that actually exists today; it is not a public provider-node installer.

ComputeMesh explores whether heterogeneous computers can cooperate as one model-aware AI inference fabric. The long-term goal is simple: choose a model and policy, while ComputeMesh handles feasibility, placement, preparation, execution, failures, verification, and auditable accounting.

## Fastest way to try the lab tooling

Clone/download the repository and use the launcher for your OS:

**Windows:** double-click `SETUP.cmd`  
**Linux:** run `./setup.sh` (or `bash setup.sh` if the executable bit was lost).

Both launchers expose the same simple menu for profile capture, trusted-LAN RTT/throughput measurement, local llama.cpp benchmarking, and the current complete test set. Model weights are never downloaded automatically.

The detailed two-computer walkthrough is in [setup/README.md](setup/README.md).

## Current implementation

Implemented foundations now include:

- cross-platform Windows/Linux Lab Setup;
- inventory, TCP network, and llama.cpp `llama-bench` measurement tooling;
- Draft-2020-12 machine-readable state/control contracts;
- deterministic Job/Reservation semantics;
- transactional SQLite reference persistence with durable idempotency, revisions, leases, restart recovery, request fingerprints, and atomic reservation → job/stage binding;
- strict transport-neutral `ControlEnvelope` validation and structured errors;
- durable handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`;
- authentication-gated node-session semantics and strict wire binding for `NodeHello`, `NodeAuthenticate`, `CapabilityNegotiation`, `NodeProfileUpdate`, `BenchmarkReport`, and `DrainRequest`;
- protocol negotiation, authenticated actor binding, optimistic session revisions, replay/conflict handling, capability/profile/benchmark readiness gates;
- the M1 reference identity path `computemesh-ed25519-v1` with short-lived challenge proofs;
- a SQLite reference identity registry with hashed enrollment tokens, stable node IDs independent of keys, rotation, and monotonic key/node revocation;
- a controlled llama.cpp RPC **research harness** for the first M1 shared-runtime experiment.

## Controlled llama.cpp M1 experiment

`runtime/llama/rpc_spike.py` is now the first executable shared-runtime experiment controller. It does **not** make upstream llama.cpp RPC a ComputeMesh protocol.

The harness can:

1. start an upstream RPC worker only on loopback/RFC1918 literal IPv4;
2. discover the exact local/RPC device names reported by the current llama.cpp build;
3. record a deterministic local-only baseline;
4. run an explicit local + RPC `layer` split with fixed device list and tensor ratios;
5. compare the exact same model/prompt by token-ID digest when available, otherwise output digest;
6. record model SHA-256, llama.cpp version, topology, placement, model-ready/request time and prefill/decode metrics without persisting raw prompt/output text.

The first experiment deliberately forces the coordinator HTTP server to `127.0.0.1`, uses `--offline`, disables automatic fitting and prompt/RPC cache surfaces, and does not use advanced tensor overrides. See [runtime/llama/README.md](runtime/llama/README.md).

**ADR 0002 remains Proposed.** The harness is infrastructure for the proof; no real shared two-node inference result has been produced yet.

## Verified real-target evidence

Existing physical-target evidence from 2026-08-21 includes:

- Windows target: RTX 3080 Laptop GPU, 16 GiB VRAM, 31.7 GiB RAM;
- Linux target: Debian 13 server, 4 logical CPU cores, 7.8 GiB RAM, CPU-only;
- Windows → internet Linux engineering TCP measurement: RTT p50 `11.884 ms`, p95 `13.369 ms`, upload p50 `42.276 Mbit/s`, download p50 `226.597 Mbit/s`;
- Windows CUDA llama.cpp 7B-Q4 benchmark: prefill `2866.127 tok/s`, decode `76.210 tok/s`;
- Linux CPU llama.cpp 0.5B-Q4 smoke: prefill `12.382 tok/s`, decode `0.201 tok/s`.

The internet network result is not a trusted-private-LAN A/B proof and is not distributed shared inference.

## Identity decision and security boundary

ADR 0005 is accepted **only for the narrow M1 reference implementation**: stable node IDs plus Ed25519 challenge proofs, short-lived enrollment, key rotation, and revocation semantics.

That does not make the identity system production-ready. Missing before public network exposure include provider/user authentication around identity APIs, OS-protected node private-key storage, active-session revocation fan-out, authenticated/encrypted transport, authorization/rate/resource limits, and production service/database operation. A copied private key is still cryptographically the same identity; signatures do not prove one physical machine.

The upstream llama.cpp RPC worker is even more restricted: it is **trusted-lab-only**. Current ComputeMesh identity/session authentication does not authenticate the upstream RPC socket. Never expose it to the public internet or an untrusted network.

`confidential_compute` is not a valid guarantee until a concrete trusted-execution/attestation design exists.

## Not implemented yet

There is still no production provider-node installer/service, no completed distributed shared-inference result, no automatic M1 scheduler/placement planner, no production Gateway/API, no production identity network service, no complete artifact/runtime/failure wire path, no billing/verification/telemetry product stack, and no signed production release/update pipeline.

## Immediate path

```text
profile + local benchmarks
        ↓
trusted private-LAN A↔B measurement
        ↓
local deterministic llama-server baseline
        ↓
explicit local + RPC layer split
        ↓
correctness + timing comparison
        ↓
activation/transfer + latency/jitter/loss measurement
        ↓
first reproducible shared two-node inference
        ↓
first machine-readable placement decision
```

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # simple Windows/Linux lab entry points
├─ setup/                 # cross-platform lab orchestration
├─ tools/benchmark/       # inventory, TCP, llama-bench adapters
├─ services/orchestrator/ # durable M0 state/control foundation
├─ services/identity/     # M1 reference enrollment/key registry
├─ protocol/              # contracts, session wire binding, Ed25519 verifier
├─ runtime/llama/         # controlled llama.cpp M1 research spike
├─ docs/                  # specifications and ADRs
└─ state.md               # canonical engineering handoff
```

For engineering details, read `state.md` first, then `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md`, and the ADRs.

## Language synchronization rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.
