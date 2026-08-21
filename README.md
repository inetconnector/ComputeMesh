# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Project stage:** M0 — contracts, benchmarking, orchestration semantics, protocol/session foundations, security, and feasibility research.  
> **Implementation status:** executable M0 benchmark tooling, machine-readable contracts, transactional Job/Reservation persistence, initial durable control handlers, and an authentication-gated node-session state machine now exist. There is still no production distributed runtime, scheduler, marketplace, billing system, credential verifier, or public provider-node software.

ComputeMesh is an experimental distributed AI inference system intended to make heterogeneous compute resources usable as one logical execution fabric. A client with limited local VRAM should eventually be able to run a model whose memory and compute requirements exceed the client machine by using approved remote compute without manually managing shards, hosts, ports, or placement.

**North Star:** the user chooses a model and policy; ComputeMesh determines feasibility, selects compatible capacity, prepares verified model partitions, executes inference, handles failures, verifies results according to risk, and produces an auditable cost record.

“The internet is your GPU” is a product metaphor, not a performance guarantee. WAN latency, bandwidth, jitter, hardware heterogeneity, provider trust, model licensing, and failure probability are first-class constraints.

## Current status

### Implemented in M0

- bilingual root documentation and ADR process;
- architecture, protocol, security, benchmark, failure, privacy, and data-model specifications;
- Draft 2020-12 machine-readable contracts for core state/control records and the first control-message payloads;
- inventory, TCP network, and llama.cpp `llama-bench` measurement tooling;
- deterministic Job/Reservation state-machine semantics;
- transactional SQLite reference persistence with durable idempotency, optimistic revisions, leases, restart recovery, request fingerprints, and schema migration;
- atomic `CommitReservation` binding from reservation to concrete job + stage;
- common control-envelope validation and structured errors;
- durable handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`;
- transport-neutral node-session lifecycle: `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- a mandatory injected `AuthenticationVerifier` interface with **no permissive default**;
- session challenge binding, credential-expiry enforcement, NodeHello/authenticated-node identity consistency, capability intersection, profile/benchmark revision gating, and external session termination for revocation signals.

### Not implemented / not yet evidenced

- real llama.cpp benchmark evidence from a target lab GPU/model;
- real two-node LAN/WAN benchmark evidence;
- production provider node agent;
- distributed runtime worker/shared inference;
- gateway/API and production scheduler;
- production orchestrator network service/database adapter;
- a production node credential format, cryptographic verifier, issuer/enrollment service, OS-protected private-key integration, rotation, or revocation backend;
- wire handlers/contracts for NodeHello/NodeAuthenticate/ProfileSync and the remaining node/runtime/artifact protocol messages;
- registry, verification, billing/ledger, telemetry, SDK, and UI;
- production deployment/update pipeline;
- public release.

The canonical engineering handoff is `state.md`.

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
Client / SDK -> Gateway / API -> Job Orchestrator
                                  |-> Scheduler + Topology
                                  |-> Registry
                                  |-> Policy / Verification
                                  v
                           Capacity reservations
                                  v
                         Provider execution mesh
                    Node A <---- streams ----> Node B
                                  v
                       Telemetry / Metering / Ledger
```

## Repository map

```text
ComputeMesh/
├─ apps/                  # planned product surfaces
├─ services/orchestrator/ # durable M0 state + initial control handlers
├─ runtime/               # planned CUDA/llama.cpp/vLLM/network integrations
├─ protocol/              # envelope, payload contracts, session semantics, tests
├─ tools/benchmark/       # inventory, TCP network, llama-bench adapter
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/
```

## Run the current M0 tooling/tests

```powershell
git clone <repository-url>
cd ComputeMesh
python -m pip install -r requirements-dev.txt
python tools/benchmark/benchmark.py --dry-run
python -m unittest discover -s tools/benchmark/tests -v
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
```

### Capture a node profile

```powershell
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

### Measure a trusted LAN path

On node B:

```powershell
python tools/benchmark/network_benchmark.py server --bind 0.0.0.0 --port 43191 --once
```

On node A:

```powershell
python tools/benchmark/network_benchmark.py client --host <NODE-B-LAN-IP> --port 43191 --profile-revision 1
```

The benchmark server has **no authentication or encryption**. Use it only on a controlled trusted LAN with firewall restriction; never expose it to the public internet.

### Measure local llama.cpp prefill/decode

```powershell
python tools/benchmark/llama_bench_adapter.py `
  --llama-bench C:\path\to\llama-bench.exe `
  --model C:\path\to\model.gguf `
  --profile-revision 1
```

A real model/hardware run is still required before making M1 performance claims.

## Protocol, persistence, and session foundations

The initial durable control path validates the common envelope and operation-specific payload, fingerprints message type + payload, then applies an atomic SQLite state effect using the envelope `request_id` as durable idempotency key. Replays have one business effect; changed payload reuse is rejected.

The first handlers cover only operations already named in `PROTOCOL.md`: `ReserveCapacity`, `CommitReservation`, and `CancelJob`.

`protocol/node_session.py` now models the documented readiness sequence and refuses to advance past authentication unless a caller supplies an `AuthenticationVerifier` that returns a valid, non-expired identity decision bound to the session challenge. **The interface is not itself a production authentication mechanism.** ADR 0005 remains Proposed.

## Runtime direction

The first proposed M1 research path is llama.cpp-oriented, wrapped behind the ComputeMesh node/worker boundary. vLLM remains a comparison/reference. ADR 0002 is still **Proposed**, not accepted.

## Immediate engineering sequence

```text
machine-readable contracts + benchmark harnesses              [implemented M0]
durable Job/Reservation state + initial handlers               [implemented M0]
common envelope + structured errors                            [implemented M0]
authentication-gated node-session semantics                    [implemented M0]
-> run inventory/network/runtime measurements on real nodes
-> select/implement concrete node credential verification via ADR 0005
-> bind NodeHello/Auth/Profile messages to the session skeleton
-> llama.cpp-oriented M1 runtime spike
-> activation-payload transport benchmark
-> shared two-node inference
-> scheduler automation
```

## Security warning

Do not expose experimental runtime RPC or benchmark endpoints directly to the public internet. Do not treat the `AuthenticationVerifier` interface as proof that node authentication is production-ready. `confidential_compute` is not a valid guarantee until a concrete trusted-execution and attestation design exists.

## Language synchronization rule

`README.md` and `README.de.md` must be updated together for every public-facing project change.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.
