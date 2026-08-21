# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Stage:** M0 — engineering/lab implementation.  
> **Important:** ComputeMesh is **not yet a production distributed-inference product**. The Windows/Linux setup below prepares the lab and benchmark workflow that actually exists today; it is not a public provider-node installer.

ComputeMesh explores whether heterogeneous computers can cooperate as one model-aware AI inference fabric. The long-term goal is simple: choose a model and policy, while ComputeMesh handles feasibility, placement, preparation, execution, failures, verification, and auditable accounting.

## Fastest way to try it

Clone or download the repository, then use the launcher for your operating system:

**Windows**

```text
Double-click SETUP.cmd
```

**Linux**

```bash
./setup.sh
```

If the executable bit was lost while downloading/extracting the repository:

```bash
bash setup.sh
```

Both launchers open the same simple menu. You do **not** need to type the underlying Python benchmark commands, create `.venv` yourself, remember profile revisions, or construct result folders.

| Option | What it does |
| --- | --- |
| 1 | Prepare this computer and capture its CPU/RAM/GPU profile |
| 2 | Wait for one trusted-LAN network test on this computer (Node B) |
| 3 | Measure RTT and throughput to the other computer (Node A) |
| 4 | Measure local llama.cpp prefill/decode performance |
| 5 | Install local test dependencies and run all current tests |

The detailed two-computer walkthrough is in [setup/README.md](setup/README.md).

## What setup handles automatically

On both Windows and Linux it:

- chooses German/English from the OS locale;
- finds Python 3.10+ and creates repository-local `.venv`;
- creates a stable random lab-node ID instead of using the hostname;
- advances profile revision only after a successful inventory capture;
- stores local config, downloads, and results under ignored `artifacts/lab/` paths;
- shows short CPU/GPU/RAM, RTT/throughput, and llama.cpp summaries;
- restricts the assisted network server to a concrete private RFC1918 address instead of `0.0.0.0`;
- removes any temporary firewall rule after the one-shot network test;
- never downloads model weights automatically.

Platform-specific convenience:

- **Windows:** missing Python can be installed user-scoped through `winget`; the network helper uses a temporary Windows `Private`/`LocalSubnet` firewall rule.
- **Linux:** missing base packages can be installed, after confirmation, through `apt`, `dnf`, `zypper`, `pacman`, or `apk`; active `firewalld` or `ufw` is handled with a temporary rule limited to the detected private subnet.

## llama.cpp setup

The setup can use an existing `llama-bench` or download an official upstream build.

- Windows selects the official Windows build appropriate to the current setup path.
- Linux dynamically selects an official Ubuntu CPU, Vulkan, or ROCm build for supported x64/arm64 cases and verifies a GitHub-provided SHA-256 asset digest when available.
- The Linux download is executed with a local wrapper for bundled libraries and is accepted only if `llama-bench --version` succeeds on that machine.
- On Linux desktops, `zenity` is used for the GGUF picker when available; otherwise the terminal asks for the path with shell completion.

Official Linux release assets currently include Ubuntu CPU, Vulkan, ROCm, OpenVINO, and SYCL variants. Automatic setup intentionally uses only the small CPU/Vulkan/ROCm decision surface needed for the M0 benchmark workflow.

## Current implementation

Implemented M0 foundations include:

- cross-platform Windows/Linux Lab Setup;
- inventory, TCP network, and llama.cpp `llama-bench` measurement tooling;
- machine-readable Draft 2020-12 contracts for core state/control records and initial message payloads;
- deterministic Job/Reservation state semantics;
- transactional SQLite reference persistence with durable idempotency, revisions, leases, restart recovery, request fingerprints, and schema migration;
- atomic `CommitReservation` binding to job + stage;
- transport-neutral control-envelope validation and structured errors;
- durable initial handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`;
- authentication-gated node-session semantics for `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- a mandatory injected `AuthenticationVerifier` boundary with no permissive default.

## Not implemented yet

There is still no production provider-node application/installer, distributed shared-inference runtime, Gateway/API, scheduler, production credential system, complete wire protocol, billing/verification/telemetry product stack, or signed release/update pipeline.

ADR 0005 (node identity) and ADR 0002 (M1 runtime baseline) remain **Proposed**, not accepted.

## Two-computer M0 path

```text
SETUP.cmd (Windows) or ./setup.sh (Linux) on both computers
        ↓
profile both machines
        ↓
measure LAN A → B and B → A
        ↓
measure llama.cpp prefill/decode on each relevant machine
        ↓
choose the concrete M1 two-node spike
        ↓
activation transport benchmark
        ↓
first correct shared two-node inference
        ↓
scheduler calibration
```

The two computers may be Windows, Linux, or one of each; the benchmark record format and the underlying Python helpers are shared.

## Security boundary

The TCP benchmark protocol has no application authentication or encryption. Use the assisted server only on a trusted private LAN. Neither launcher makes the experimental runtime safe for public-Internet exposure.

The existing `AuthenticationVerifier` is a semantic interface, not a production credential system. `confidential_compute` is not a valid guarantee until a concrete trusted-execution/attestation design exists.

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd              # Windows M0 entry point
├─ setup.sh               # Linux M0 entry point
├─ setup/                 # shared helper + Windows/Linux launchers
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
