# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Stage:** M0 — engineering/lab implementation.  
> **Important:** ComputeMesh is **not yet a production distributed-inference product**. The Windows setup below prepares the currently implemented lab/benchmark workflow; it is not a public provider-node installer.

ComputeMesh explores whether heterogeneous computers can cooperate as one model-aware AI inference fabric. The long-term goal is simple: choose a model and policy, while ComputeMesh handles feasibility, placement, preparation, execution, failure handling, verification, and auditable accounting.

## Fastest way to try the current project on Windows

1. Clone or download this repository.
2. Open the ComputeMesh folder.
3. **Double-click `SETUP.cmd`.**
4. Choose what you want to do from the menu.

That is the normal M0 entry point. You do **not** need to type Python commands, create a virtual environment, remember profile revisions, or manually build benchmark command lines.

The menu provides:

| Option | What it does |
| --- | --- |
| 1 | Prepare this computer and capture its CPU/RAM/GPU profile |
| 2 | Wait for a trusted-LAN network test on this computer (Node B) |
| 3 | Measure RTT and throughput to the other computer (Node A) |
| 4 | Measure local llama.cpp prefill/decode performance |
| 5 | Install local test dependencies and run all current tests |

Direct launchers are also available under `setup/`: `NODE.cmd`, `NETWORK-SERVER.cmd`, `NETWORK-CLIENT.cmd`, `LLAMA-BENCH.cmd`, and `TESTS.cmd`.

See [setup/README.md](setup/README.md) for the two-computer walkthrough.

## What the Windows Lab Setup handles automatically

- detects German/English from Windows;
- finds Python 3.10+ or attempts a user-scoped Python install with `winget`;
- creates an isolated `.venv` inside the repository;
- creates a stable random lab-node ID instead of using the Windows hostname;
- advances profile revisions only after a successful inventory capture;
- stores local configuration and results under ignored `artifacts/lab/` paths;
- shows short CPU/GPU/RAM, RTT/throughput, and llama.cpp performance summaries;
- for the LAN server, opens port 43191 only temporarily for the selected private address, Windows `Private` profile, and `LocalSubnet`, then removes the rule;
- can download the latest official Windows llama.cpp release from `ggml-org/llama.cpp` and verify a GitHub-provided SHA-256 digest when available;
- remembers a successfully used `llama-bench.exe` and GGUF path locally for the next run.

The setup does **not** download model weights automatically. You select a local `.gguf` file so licensing, model size, and model choice remain explicit.

## Current implementation

Implemented M0 foundations include:

- inventory, TCP network, and llama.cpp `llama-bench` measurement tooling;
- machine-readable Draft 2020-12 contracts for core state/control records and initial message payloads;
- deterministic Job/Reservation state semantics;
- transactional SQLite reference persistence with durable idempotency, revisions, leases, restart recovery, request fingerprints, and schema migration;
- atomic `CommitReservation` binding to job + stage;
- transport-neutral control-envelope validation and structured errors;
- durable initial handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`;
- authentication-gated node-session semantics for `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- a mandatory injected `AuthenticationVerifier` boundary with no permissive default;
- the Windows M0 Lab Setup described above.

## Not implemented yet

There is still no production:

- provider-node application/installer;
- distributed runtime or shared two-node inference result;
- Gateway/API or scheduler;
- production orchestrator service/database;
- node enrollment/key/credential verifier, issuer, rotation, or revocation backend;
- full NodeHello/Auth/Profile wire binding;
- registry, verification, billing/ledger, telemetry, SDK, dashboard, or desktop product;
- signed release/update pipeline.

ADR 0005 (node identity) and ADR 0002 (M1 runtime baseline) remain **Proposed**, not accepted.

## Two-computer M0 path

```text
SETUP.cmd on both computers
        ↓
profile both machines
        ↓
measure LAN A → B and B → A
        ↓
measure llama.cpp prefill/decode on each machine
        ↓
choose the concrete M1 two-node spike
        ↓
activation transport benchmark
        ↓
first correct shared two-node inference
        ↓
scheduler calibration
```

Shipping the setup does not itself provide the real two-node evidence; those measurements must be run on actual target machines.

## Security boundary

The TCP benchmark server has no application authentication or encryption. The Windows setup therefore restricts the assisted server flow to a private RFC1918 LAN and a temporary `LocalSubnet` firewall rule. Do not expose benchmark/runtime endpoints to the public internet.

The existing `AuthenticationVerifier` is a semantic interface, not a production credential system. `confidential_compute` is not a valid guarantee until a concrete trusted-execution/attestation design exists.

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd              # simplest Windows M0 entry point
├─ setup/                 # Windows lab workflow + direct launchers
├─ tools/benchmark/       # inventory, TCP network, llama-bench adapter
├─ services/orchestrator/ # durable M0 state + initial control handlers
├─ protocol/              # contracts, envelope, session semantics, tests
├─ apps/                  # planned product applications
├─ runtime/               # planned/runtime research integrations
├─ docs/                  # specifications and ADRs
└─ state.md               # canonical engineering handoff
```

For engineering details, read `state.md` first, then `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md`, and the ADRs.

## Language synchronization rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.
