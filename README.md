# ComputeMesh

**Languages:** **English** | [Deutsch](README.de.md)

> **Stage:** M0 — engineering/lab implementation moving toward the first M1 runtime proof.  
> **Important:** ComputeMesh is **not yet a production distributed-inference product**. The Windows/Linux setup below prepares the lab/benchmark workflow that actually exists today; it is not a public provider-node installer.

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
- The Linux download is executed with a local wrapper for bundled libraries and is accepted only if `llama-bench --help` starts successfully on that machine.
- On Linux desktops, `zenity` is used for the GGUF picker when available; otherwise the terminal asks for the path with shell completion.

Model weights are never downloaded automatically.

## Current implementation

Implemented foundations include:

- cross-platform Windows/Linux Lab Setup;
- inventory, TCP network, and llama.cpp `llama-bench` measurement tooling;
- machine-readable Draft 2020-12 contracts for core state/control records and initial message payloads;
- deterministic Job/Reservation state semantics;
- transactional SQLite reference persistence with durable idempotency, revisions, leases, restart recovery, request fingerprints, and schema migration;
- atomic `CommitReservation` binding to job + stage;
- transport-neutral control-envelope validation and structured errors;
- durable initial handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`;
- authentication-gated node-session semantics for `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY -> DRAINING/CLOSED`;
- strict node-session wire contracts and envelope-to-session binding for `NodeHello`, `NodeAuthenticate`, `CapabilityNegotiation`, `NodeProfileUpdate`, `BenchmarkReport`, and `DrainRequest`;
- session protocol negotiation, authenticated actor binding, optimistic revisions, exact replay handling, semantic request-ID conflict detection, and an injected benchmark-readiness policy;
- an M1 reference node-identity path using `computemesh-ed25519-v1` challenge signatures behind the mandatory `AuthenticationVerifier` boundary;
- a SQLite reference identity registry with short-lived hashed enrollment tokens, stable random node IDs, public-key lookup, key rotation, and monotonic key/node revocation.

The Ed25519 proof is bound to session ID, per-session challenge, stable node ID, key ID, protocol version, proof lifetime, and the accepted `NodeHello` semantics. The control plane stores public keys only; it never stores node private keys.

## Verified real-target evidence

The lab flow has been exercised on real Windows and Linux targets:

- Windows target: RTX 3080 Laptop GPU, 16 GiB VRAM, 31.7 GiB RAM.
- Linux target: Debian 13 server, 4 logical CPU cores, 7.8 GiB RAM, no GPU detected.
- Windows -> internet Linux TCP benchmark: RTT p50 `11.884 ms`, RTT p95 `13.369 ms`, upload p50 `42.276 Mbit/s`, download p50 `226.597 Mbit/s`.
- Windows CUDA llama.cpp benchmark with a 7B Q4 GGUF: prefill `2866.127 tok/s`, decode `76.210 tok/s`.
- Linux CPU llama.cpp smoke with a 0.5B Q4 GGUF: prefill `12.382 tok/s`, decode `0.201 tok/s`.

The internet TCP test was intentionally run through the engineering CLI with a temporary source-limited firewall rule, not through the unauthenticated trusted-LAN UI. It is real target-machine evidence, but it is not a private-LAN A/B proof and not distributed shared inference.

## Identity decision and security boundary

ADR 0005 is now **accepted for the narrow M1 reference implementation**: stable node IDs plus Ed25519 challenge proofs, short-lived enrollment, key rotation, and revocation semantics.

That does **not** mean the identity system is production-ready. Still missing before public network exposure are:

- provider/user authentication around enrollment/rotation/revocation APIs;
- OS-protected node private-key storage (for example the supported Windows and Linux node-agent paths);
- active-session revocation fan-out;
- authenticated/encrypted control transport;
- rate/resource limits and abuse controls;
- production service/database operations;
- hardware attestation or Sybil resistance.

A revoked node/key is rejected for new authentication. Existing authenticated sessions still require an external revocation signal to terminate them. A cloned private key remains cryptographically the same identity; signatures alone do not prove one physical machine.

The trusted-LAN TCP benchmark still has no application authentication or encryption. Use its assisted server only on a trusted private LAN. `confidential_compute` is not a valid guarantee until a concrete trusted-execution/attestation design exists.

## Not implemented yet

There is still no production provider-node application/installer, distributed shared-inference runtime, Gateway/API, scheduler, production identity network service, complete wire protocol, billing/verification/telemetry product stack, or signed release/update pipeline.

ADR 0002 (M1 runtime baseline) remains **Proposed**. The next software gate is the narrow llama.cpp-oriented M1 runtime spike behind the ComputeMesh boundary.

## Two-computer path

```text
SETUP.cmd (Windows) or ./setup.sh (Linux) on both computers
        ↓
profile both machines
        ↓
measure LAN A → B and B → A
        ↓
measure llama.cpp prefill/decode on each relevant machine
        ↓
choose/validate the narrow M1 runtime baseline
        ↓
activation/remote-stage transport experiment
        ↓
first correct shared two-node inference
        ↓
scheduler calibration
```

The two computers may be Windows, Linux, or one of each; the benchmark record format and the underlying Python helpers are shared.

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd              # Windows M0 entry point
├─ setup.sh               # Linux M0 entry point
├─ setup/                 # shared helper + Windows/Linux launchers
├─ tools/benchmark/       # inventory, TCP network, llama-bench adapter
├─ services/orchestrator/ # durable M0 state + initial control handlers
├─ services/identity/     # M1 reference enrollment/key registry
├─ protocol/              # contracts, session wire binding, Ed25519 verifier, tests
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
