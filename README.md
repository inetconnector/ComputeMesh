# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Project stage:** M0 — contracts, benchmarking, orchestration semantics, protocol foundations, security, and feasibility research.  
> **Implementation status:** executable M0 benchmark tooling, machine-readable contracts, transactional Job/Reservation persistence, the transport-neutral control envelope, and the first message-specific control handlers now exist. There is still no production distributed runtime, scheduler, marketplace, billing system, or public provider-node software.

ComputeMesh is an experimental distributed AI inference system intended to make heterogeneous compute resources usable as one logical execution fabric. A client with limited local VRAM should eventually be able to run a model whose memory and compute requirements exceed the client machine by using approved remote compute without manually managing shards, hosts, ports, or placement.

**North Star:** the user chooses a model and policy; ComputeMesh determines feasibility, selects compatible capacity, prepares verified model partitions, executes inference, handles failures, verifies results according to risk, and produces an auditable cost record.

“The internet is your GPU” is a product metaphor, not a performance guarantee. WAN latency, bandwidth, jitter, hardware heterogeneity, provider trust, model licensing, and failure probability are first-class constraints.

## Current status

### Implemented in M0

- bilingual root documentation and ADR process;
- architecture, protocol, security, benchmark, failure, privacy, and data-model specifications;
- Draft 2020-12 schemas for node profiles, benchmark results, model/shard manifests, reservations, jobs, the common control envelope, structured errors, and the first control-message payloads;
- standard-library Python inventory benchmark collector;
- TCP network microbenchmark for connection setup, RTT p50/p95, upload/download throughput, and raw samples;
- llama.cpp `llama-bench` adapter that maps prompt-processing and generation measurements to ComputeMesh prefill/decode benchmark records;
- deterministic Job/Reservation state-machine semantics;
- transactional SQLite reference persistence with durable idempotency, optimistic revisions, lease persistence/expiry, stale-writer rejection, rollback, and restart recovery;
- SQLite schema migration v1 → v2 with durable request fingerprints;
- atomic `CommitReservation` binding from reservation to concrete job + stage;
- JSON-Schema-based Job/Reservation admission;
- transport-neutral common control-envelope parsing with version/time/shape checks and structured errors;
- message-specific payload validation and durable handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`.

### Not implemented / not yet evidenced

- real llama.cpp benchmark evidence from a target lab GPU/model;
- real two-node LAN/WAN benchmark evidence;
- production provider node agent;
- distributed runtime worker/shared inference;
- gateway/API and production scheduler;
- production orchestrator network service/database adapter;
- authenticated node sessions and authorization;
- the remaining node/runtime/artifact protocol messages beyond the initial three handlers;
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

For dense pipeline execution, normal inter-node token traffic is expected to be stage activations/results. KV cache normally remains with the layers that own it; KV movement is primarily a migration, recovery, or rebalancing concern.

## Repository map

```text
ComputeMesh/
├─ apps/                  # planned product surfaces
├─ services/orchestrator/ # M0 state machine, persistence, admission, handlers
├─ runtime/               # planned CUDA/llama.cpp/vLLM/network integrations
├─ protocol/              # control envelope, payload contracts, schemas, tests
├─ tools/benchmark/       # inventory, TCP network, llama-bench adapter
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/                  # architecture/security/benchmark/ADR documents
```

## Run the current M0 tooling

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

The adapter is a measurement adapter, not evidence that M1 has passed. A real model/hardware run is still required.

## Protocol and persistence foundations

`services/orchestrator/persistence.py` is an M0 SQLite reference proving transactional state effects, durable deduplication, optimistic revision checks, restart-safe replay, leases, and atomic reservation-to-job/stage binding. SQLite is **not** selected as the production database.

`protocol/control.py` implements the common control-envelope semantics without selecting gRPC, QUIC, HTTP, or another transport. The initial message layer validates and dispatches only three operations already defined by `PROTOCOL.md`:

- `ReserveCapacity`;
- `CommitReservation`;
- `CancelJob`.

For these operations, the application carries the envelope `request_id` into durable idempotency storage and also fingerprints message type + payload. Replaying the same request has one business effect; reusing the same request ID with a changed payload is rejected as an idempotency conflict.

**Authentication and authorization are not implemented by these handlers.** Actor identity remains untrusted until the node-identity/session design is implemented.

## Runtime direction

The first proposed M1 research path is llama.cpp-oriented, wrapped behind the ComputeMesh node/worker boundary. vLLM remains a comparison/reference. ADR 0002 is still **Proposed**, not accepted.

## Immediate engineering sequence

```text
machine-readable contracts + inventory harness               [implemented M0]
transactional Job/Reservation persistence + schema admission  [implemented M0]
common control envelope + structured errors                   [implemented M0]
initial documented control handlers                           [implemented M0]
TCP lab network microbenchmark                                [implemented M0]
llama-bench prefill/decode adapter                             [implemented M0]
-> run inventory/network/runtime measurements on real nodes
-> llama.cpp-oriented M1 runtime spike
-> authenticated node-session skeleton
-> remaining node/runtime/artifact protocol handlers
-> activation-payload transport benchmark
-> shared two-node inference
-> scheduler automation
```

## Security warning

Do not expose experimental runtime RPC or benchmark endpoints directly to the public internet. `confidential_compute` is not a valid guarantee until a concrete trusted-execution and attestation design exists.

## Language synchronization rule

`README.md` and `README.de.md` must be updated together for every public-facing project change.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.
