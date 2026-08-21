# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Project stage:** M0 — contracts, benchmarking, orchestration semantics, protocol foundations, security, and feasibility research.  
> **Implementation status:** executable M0 inventory/network benchmarks, machine-readable contracts, transactional Job/Reservation persistence, and a transport-neutral control-envelope parser now exist. There is still no production runtime, scheduler, marketplace, billing system, or public provider-node software.

ComputeMesh is an experimental distributed AI inference system intended to make heterogeneous compute resources usable as one logical execution fabric. A client with limited local VRAM should eventually be able to run a model whose memory and compute requirements exceed the client machine by using approved remote compute without manually managing shards, hosts, ports, or placement.

**North Star:** the user chooses a model and policy; ComputeMesh determines feasibility, selects compatible capacity, prepares verified model partitions, executes inference, handles failures, verifies results according to risk, and produces an auditable cost record.

“The internet is your GPU” is a product metaphor, not a performance guarantee. WAN latency, bandwidth, jitter, hardware heterogeneity, provider trust, model licensing, and failure probability are first-class constraints.

## Current status

### Implemented

- bilingual root documentation and ADR process;
- architecture, protocol, security, benchmark, failure, privacy, and data-model specifications;
- Draft-2020-12 schemas for node profile, benchmark result, model/shard manifests, reservation, job, common control envelope, and structured protocol errors;
- standard-library Python inventory benchmark collector;
- standard-library TCP network microbenchmark for connection setup, small-frame RTT p50/p95, upload throughput, download throughput, and raw samples;
- deterministic Job/Reservation state-machine semantics;
- transactional SQLite M0 persistence with durable idempotency, revisions, lease persistence/expiry, stale-writer rejection, rollback, and restart recovery;
- JSON-Schema-based Job/Reservation admission;
- transport-neutral common control-envelope parser with version/time/shape checks and structured errors;
- tests for benchmark, orchestrator, persistence/concurrency/restart, admission, protocol envelope, and protocol schemas.

### Not implemented

- production provider node agent;
- runtime worker or distributed inference execution;
- gateway/API;
- production scheduler;
- production orchestrator network service/database adapter;
- authenticated node sessions and authorization;
- message-specific node/orchestrator protocol handlers;
- registry, verification, billing/ledger, telemetry, SDK, UI;
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
├─ services/orchestrator/ # M0 state machine, persistence, schema admission
├─ runtime/               # planned CUDA/llama.cpp/vLLM/network integrations
├─ protocol/              # control envelope, schemas, tests
├─ tools/benchmark/       # inventory + TCP network benchmark
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/                  # architecture/security/benchmark/ADR documents
```

## Run the current M0 tooling

Python 3.10+ is sufficient for the standard-library tools. JSON-Schema tests/admission use `jsonschema`.

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

The benchmark server has **no authentication or encryption** and defaults to loopback. Bind it to a LAN interface only for a controlled test, restrict the port with the firewall, and never expose it to the public internet.

Results are written below `artifacts/benchmark/` and use the existing benchmark-result contract.

## Protocol and persistence foundations

`services/orchestrator/persistence.py` is an M0 SQLite reference proving atomic state/idempotency effects, optimistic revision checks, restart-safe replay, leases, and stale-writer rejection. SQLite is **not** selected for production; PostgreSQL remains the control-plane direction.

`protocol/control.py` implements the common control-envelope semantics from `PROTOCOL.md` without selecting gRPC, QUIC, HTTP, or another transport. Authentication, authorization, message-specific payload handlers, and capability negotiation remain future work.

## Runtime direction

The first proposed M1 research path is llama.cpp-oriented, wrapped behind the ComputeMesh node/worker boundary. vLLM remains a comparison/reference. ADR 0002 is still **Proposed**, not accepted.

## Immediate engineering sequence

```text
machine-readable contracts + inventory harness              [implemented M0]
transactional Job/Reservation persistence + schema admission [implemented M0]
common control envelope + structured errors                  [implemented M0]
TCP lab network microbenchmark                               [implemented M0]
-> run inventory + network measurements on two real nodes
-> local runtime prefill/decode benchmark adapter
-> llama.cpp-oriented M1 runtime spike
-> message-specific protocol handlers
-> authenticated node-session skeleton
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
