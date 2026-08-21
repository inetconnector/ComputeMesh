# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Project stage:** M0 — contracts, benchmarking, orchestration semantics, protocol foundations, security, and feasibility research.  
> **Implementation status:** executable M0 tooling, machine-readable contracts, transactional Job/Reservation persistence, and a transport-neutral control-envelope parser now exist. There is still no production runtime, scheduler, marketplace, billing system, or public provider-node software.

ComputeMesh is an experimental distributed AI inference system intended to make heterogeneous compute resources usable as one logical execution fabric. A client with limited local VRAM should eventually be able to run a model whose memory and compute requirements exceed the client machine by using approved remote compute without manually managing shards, hosts, ports, or placement.

**North Star:** the user chooses a model and policy; ComputeMesh determines feasibility, selects compatible capacity, prepares verified model partitions, executes inference, handles failures, verifies results according to risk, and produces an auditable cost record.

“The internet is your GPU” is a product metaphor, not a performance guarantee. WAN latency, bandwidth, jitter, hardware heterogeneity, provider trust, model licensing, and failure probability are first-class constraints.

## Current status

### Implemented

- bilingual root documentation and ADR process;
- architecture, protocol, security, benchmark, failure, privacy, and data-model specifications;
- JSON Schema Draft 2020-12 contracts for node profile, benchmark result, model manifest, shard manifest, reservation, job, common control envelope, and structured protocol errors;
- concrete example manifests/jobs/reservations;
- a standard-library Python inventory benchmark collector with NVIDIA GPU/VRAM/driver discovery when `nvidia-smi` is available;
- deterministic in-memory Job/Reservation state-machine semantics;
- a transactional SQLite M0 persistence adapter with monotonic revisions, durable idempotency, lease persistence/expiry, stale-writer rejection, rollback, and restart recovery;
- JSON-Schema-based Job/Reservation admission before durable creation;
- a transport-neutral protocol parser for the common control envelope with version-major checks, expiry/clock-skew enforcement, unknown-field rejection, and structured errors;
- unit tests for benchmark, state-machine, persistence/concurrency/restart, contract admission, control-envelope behavior, and protocol schemas.

### Not implemented

- production provider node agent;
- runtime worker or distributed inference execution;
- gateway/API;
- production scheduler;
- production orchestrator network service and production database adapter;
- authenticated node sessions and authorization;
- message-specific node/orchestrator protocol handlers;
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

## Repository map

```text
ComputeMesh/
├─ apps/                 # planned node/desktop/dashboard/admin surfaces
├─ services/
│  └─ orchestrator/      # M0 state machine, SQLite reference persistence, schema admission
├─ runtime/              # planned CUDA/llama.cpp/vLLM/network integrations
├─ protocol/
│  ├─ control.py         # transport-neutral common control-envelope parser
│  ├─ schemas/           # machine-readable M0 contracts
│  ├─ examples/          # contract examples
│  └─ tests/             # protocol and schema tests
├─ tools/
│  └─ benchmark/         # executable M0 inventory collector + unit tests
├─ models/
├─ sdk/
├─ tests/
├─ deploy/
├─ research/
└─ docs/
   └─ adr/               # architecture decisions
```

## Run the current M0 tooling

Python 3.10+ is sufficient for the standard-library collectors/state store. JSON-Schema tests and admission use `jsonschema`.

```powershell
git clone <repository-url>
cd ComputeMesh
python -m pip install -r requirements-dev.txt
python tools/benchmark/benchmark.py --dry-run
python -m unittest discover -s tools/benchmark/tests -v
python -m unittest discover -s services/orchestrator/tests -v
python -m unittest discover -s protocol/tests -v
```

To write a lab profile:

```powershell
python tools/benchmark/benchmark.py --node-id lab-node-a --profile-revision 1
```

Benchmark output is written below `artifacts/benchmark/` and ignored by Git. The collector deliberately excludes hostnames, GPU UUIDs, prompts, outputs, and other unnecessary identifiers.

## Orchestrator reference persistence

`services/orchestrator/persistence.py` is intentionally an M0 reference adapter. SQLite transactions prove atomic state/idempotency effects, optimistic revision checks, durable replay results across restart, reservation lease persistence/expiry, and stale-writer rejection. This does **not** select SQLite for production; PostgreSQL remains the control-plane direction.

`services/orchestrator/contracts.py` validates initial Job/Reservation documents against repository JSON Schemas before durable admission.

## Protocol foundation

`protocol/control.py` implements the common control-envelope semantics from `PROTOCOL.md` without selecting a wire transport. It checks the supported major version, identifiers, expected revision shape, timestamps, expiry, bounded clock skew, and unknown fields, and returns structured machine-readable errors.

Higher minor versions are not automatically rejected at the base-envelope layer; capability negotiation remains separate. Authentication, authorization, message-specific payload validation, and gRPC/QUIC/HTTP transport binding are not implemented yet.

## Runtime direction

The first proposed M1 research path is llama.cpp-oriented, wrapped behind the ComputeMesh node/worker boundary. vLLM remains a comparison/reference for coordinated datacenter-style serving. ADR 0002 is still **Proposed**, not accepted.

Control and data transports are also still under evaluation. Transport encryption must never be confused with confidential execution on a provider-controlled host.

## Immediate engineering sequence

```text
machine-readable contracts + inventory harness              [implemented M0]
transactional Job/Reservation persistence + schema admission [implemented M0]
common control envelope + structured errors                  [implemented M0]
-> two-node lab profiles
-> local/runtime prefill-decode benchmark adapter
-> llama.cpp-oriented M1 runtime spike
-> message-specific protocol handlers
-> authenticated node-session skeleton
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
