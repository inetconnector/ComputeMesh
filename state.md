# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, durable orchestration, node-session wire/readiness binding, lab/runtime measurement tooling, Windows/Linux lab UX, and first real Windows↔Linux target evidence  
**Production services/runtime:** none  
**Public release:** none

This file records current engineering facts, evidence boundaries, and next actions.

## Repository

- repository: `inetconnector/ComputeMesh`
- default branch: `main`
- documentation v0.2: `cf85a47`
- contracts/benchmark bootstrap: `7df5b4e`
- transactional persistence/schema admission: `bfea175`
- control envelope/structured errors: `9ed33be`
- TCP network microbenchmark: `197a1ad`
- llama-bench prefill/decode adapter: `6b0356a`
- initial durable control handlers: `9bb4a72` + restriction `b23bf60`
- authentication-gated node-session semantics: `d7a110e`
- one-click Windows Lab Setup: `72773df` + UX/UAC hardening `cfe39a8`
- Linux Lab Setup: `3c99457`
- real target-machine smoke/fix pass: merged in `86ea6a7`; PR `#1` is merged/closed and its feature branch has been deleted
- initial node-session wire binding: `5d9e8ce` plus protocol/documentation hardening on `m0/node-session-wire-binding`

## What exists

- synchronized English/German root READMEs;
- architecture/protocol/security/benchmark/failure/privacy/data-model documentation and ADR process;
- Draft 2020-12 machine-readable contracts;
- node inventory, TCP network, and llama-bench measurement tooling;
- deterministic Job/Reservation state semantics;
- transactional SQLite reference persistence with durable idempotency, revisions, leases, restart recovery, request fingerprints, schema migration, and atomic reservation → job/stage binding;
- transport-neutral control envelope, structured errors, and first durable handlers (`ReserveCapacity`, `CommitReservation`, `CancelJob`);
- authentication-gated node-session state machine with a mandatory injected verifier boundary and no permissive default;
- strict node-session payload contracts for `NodeHello`, `NodeAuthenticate`, `CapabilityNegotiation`, `NodeProfileUpdate`, `BenchmarkReport`, and `DrainRequest`;
- transport-neutral `ControlEnvelope` → `NodeSession` binding with protocol-version negotiation, authenticated actor binding, optimistic session revisions, exact request replay, semantic request-ID conflict detection, profile/node binding, and injected benchmark-readiness policy;
- Windows M0 Lab Setup with `SETUP.cmd` and direct `.cmd` role launchers;
- Linux M0 Lab Setup with root `setup.sh`, direct `.sh` launchers, package-manager support, private-interface/firewall handling, and official llama.cpp Linux asset selection.

## Node-session wire/readiness behavior

The initial M0 session wire subset deliberately remains separate from the durable orchestration message dispatcher.

- `NodeHello` payload version must match its common envelope; unsupported protocol major is rejected and a higher compatible minor is negotiated down to the current local minor.
- `NodeAuthenticate` carries only auth method + bounded opaque credential. Credential meaning is owned by the injected `AuthenticationVerifier`.
- Authentication advances only if verifier-confirmed `node_id` matches an advertised node ID (when present) and the envelope `actor_id`.
- Every later session message must use the authenticated node as `actor_id`.
- First-time messages require `expected_revision == current session revision`.
- Successful request IDs are fingerprinted for the life of the session: exact replay returns the original snapshot; changed semantic reuse is rejected.
- `CapabilityNegotiation` cannot add a capability absent from either peer and cannot silently drop configured required capabilities.
- `NodeProfileUpdate` reuses the full node-profile v1 schema; its `node_id` must match the authenticated node.
- `BenchmarkReport` reuses the benchmark-result v1 schema and must match the synced profile revision.
- Benchmark readiness is decided by an injected `BenchmarkAcceptancePolicy`; there is no accept-all default and several accepted reports may be required before `READY`.
- `DrainRequest` binds its reason to the existing `READY -> DRAINING` transition.

This is not enrollment, production authentication, general authorization, durable network-session persistence, or a network listener. ADR 0005 remains Proposed.

## Cross-platform Lab Setup behavior

Shared behavior:

- German/English locale selection;
- Python 3.10+ and repository-local `.venv`;
- stable random non-hostname lab node ID;
- profile revision advances only after successful inventory;
- config/results/downloads below ignored `artifacts/lab/`;
- concise inventory/network/llama summaries;
- one-shot private-RFC1918 network server;
- no automatic model-weight download.

Windows-specific:

- user-scoped Python installation attempt via `winget`;
- temporary Windows `Private` + `LocalSubnet` firewall rule;
- Windows file pickers;
- official Windows llama.cpp package path.

Linux-specific:

- dependency installation after confirmation via `apt`, `dnf`, `zypper`, `pacman`, or `apk`;
- private LAN discovery through `iproute2`;
- temporary runtime `firewalld` rich rule or temporary `ufw` source-subnet rule when that firewall is active;
- concrete private-IP bind even when no supported firewall frontend is active;
- official upstream Ubuntu CPU/Vulkan/ROCm asset selection for supported x64/arm64 cases;
- GitHub-provided SHA-256 verification when available;
- generated local `LD_LIBRARY_PATH` wrapper and `llama-bench --help` acceptance check;
- `zenity` GGUF picker when available, terminal path fallback otherwise.

This remains a **lab workflow**, not a production provider installer.

## Verified implementation evidence

Benchmark blocks:

- inventory tests: 3/3;
- TCP network benchmark tests: 4/4;
- llama-bench adapter tests: 6/6;
- loopback network result and converted llama-bench fixture results validate against benchmark-result schema.

Control/orchestration evidence:

- control/orchestrator handler + persistence regression workspace: 37/37.

Current protocol/session evidence:

- complete local protocol regression: **53/53 passing**;
- existing common-envelope + durable-message-contract + schema tests remain green;
- node-session semantic tests: **17/17**;
- new session-message contract tests: **6/6**;
- new envelope→session wire-binding tests: **15/15**;
- relevant protocol Python files pass `py_compile`;
- negative coverage includes unsupported protocol major, minor-version binding, authentication actor mismatch, later actor mismatch, stale session revision, exact replay, changed request-ID reuse, capability injection, profile/node mismatch, stale benchmark revision, rejected readiness, multi-report readiness, drain ordering, and unsupported message family.

Previously verified shared/Windows setup evidence:

- `setup/lab.py` unit tests: 7/7;
- Windows script invariant/static tests: 5/5;
- prior combined setup tests: 12/12;
- synthetic helper smoke flow inventory → network-client → llama-adapter → persisted config: passed.

Linux setup evidence:

- Linux-specific automated tests: 6/6 passing on a real Linux environment;
- Bash syntax for root/direct launchers and `setup/linux.sh`: passing;
- real Linux private RFC1918 interface/subnet detection: passing in the development environment;
- release-asset selection fixtures for x64 Vulkan, x64 ROCm, and arm64 CPU: passing;
- Bash frontend smoke routing with synthetic helper/results: Node, network client, network server, llama workflow, and German menu all passed.

Real target-machine evidence from 2026-08-21:

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: `supersrv-trixie`, `lab-144a13f1`, Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU device detected.
- Linux repository deployment over SSH exposed and fixed CRLF archive/export behavior by adding `.gitattributes`; `./setup.sh help` works on the real server after LF-safe archive extraction.
- Windows direct launcher bug fixed: `setup.ps1` now preserves requested `-Mode`/`-Language` across dot-sourcing instead of falling back to menu.
- Windows lab helper invocation bug fixed: PowerShell `Invoke-Lab` no longer uses `$Args`, avoiding collision with PowerShell automatic `$args`.
- Windows `.venv` creation now tolerates a concurrent starter completing the venv first.
- Linux `download_llama` bug fixed: `runtime` and `tmp` are initialized on separate lines under `set -u`.
- Linux llama.cpp acceptance fixed from unsupported `llama-bench --version` to supported `llama-bench --help`.
- Windows direct `setup/TESTS.cmd`: passed 13 benchmark tests, 34 orchestrator tests, 29 protocol tests, 19 setup tests, with 6 Linux-specific tests skipped on Windows because Bash is unavailable there. This was recorded before the new session-wire tests increased the protocol suite to 53.
- Windows direct `setup/NODE.cmd`: passed and captured profile at `artifacts/lab/lab-d6332cbe/20260821-133030Z-inventory`.
- Linux direct `setup/TESTS.sh` on `supersrv-trixie`: passed 13 benchmark tests, 34 orchestrator tests, 29 protocol tests, and 19 setup tests. This was recorded before the new session-wire tests increased the protocol suite to 53.
- Linux direct `setup/NODE.sh` on `supersrv-trixie`: passed and captured profile at `/root/ComputeMesh/artifacts/lab/lab-144a13f1/20260821-133107Z-inventory`.
- Real Windows -> internet Linux TCP benchmark, source-limited by a temporary `ufw` rule and removed afterwards: RTT p50 11.884 ms, RTT p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s. Local artifact: `artifacts/lab/lab-d6332cbe/20260821-133137Z-network`.
- Real Windows CUDA llama.cpp benchmark using `qwen2.5-coder-7b-instruct-q4_k_m.gguf` and existing llama.cpp b9987 CUDA build: prefill 2866.127 tokens/s for 512 prompt tokens; decode 76.210 tokens/s for 128 generated tokens; backend CUDA; artifact `artifacts/lab/lab-d6332cbe/20260821-133336Z-llama`.
- Real Linux CPU llama.cpp smoke using official downloaded llama.cpp b10549 CPU build plus `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tokens/s for 128 prompt tokens; decode 0.201 tokens/s for 32 generated tokens; backend CPU; server artifact `/root/ComputeMesh/artifacts/lab/lab-144a13f1/20260821-134100Z-llama-cpu-smoke`, mirrored locally below `artifacts/lab/server-supersrv-trixie/`.

**Evidence boundary:** the Windows↔Linux measurements are real target evidence, but not a trusted private-LAN two-computer test. The Linux server is on the public internet, so the public network measurement was intentionally run through the engineering CLI with a temporary source-limited firewall rule, not through the unauthenticated LAN UI flow. The new node-session wire binding has only local semantic/schema evidence; it is not production auth and has not been exposed as a network service. No distributed shared inference exists yet.

## What does not exist / is not yet evidenced

- trusted private-LAN A↔B results using the assisted LAN UI;
- production provider-node application/service/installer;
- distributed runtime/shared inference;
- Gateway/API/scheduler;
- production orchestrator network service/database adapter;
- concrete production node credential verifier, enrollment/issuer, OS-protected key storage, rotation, and revocation lifecycle;
- authorization policy beyond authenticated node-actor consistency;
- network transport binding for the session/control protocol;
- remaining availability/job/artifact/runtime/result/failure/heartbeat wire operations required by M1;
- registry/verification/billing/telemetry/SDK/UI;
- signed production release/update system.

## ADR status

Accepted only:

- ADR 0001 — repository bootstrap.

Still proposed:

- ADR 0002 — M1 runtime baseline;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity;
- ADR 0005 — node identity/key lifecycle;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

Neither the Lab Setup nor the session/wire skeleton accepts ADR 0002/0005 by implication.

## Next actions in order

1. When two machines on the same trusted private LAN are available, run the assisted A→B and B→A LAN workflow and retain the evidence. This is a lab-evidence task and no longer blocks hardware-independent protocol work.
2. Specify and decide the concrete ADR-0005 M1 node identity/credential path, including enrollment, challenge proof, short-lived session credential, OS-protected private-key storage, rotation, and revocation semantics.
3. Implement the selected ADR-0005 verifier/enrollment prototype behind the existing no-default `AuthenticationVerifier` boundary; add replay/expiry/rotation/revocation negative tests.
4. Use the measured llama.cpp evidence to decide/accept or reject ADR 0002 for the narrow M1 runtime baseline.
5. Execute the first controlled llama.cpp-oriented remote-stage/runtime spike behind the ComputeMesh boundary; do not expose upstream experimental RPC directly as the public node protocol.
6. Add activation-payload-size benchmarks plus controlled latency/jitter/loss experiments.
7. Bind the minimum remaining reservation/job/artifact/runtime/failure messages required by that exact M1 spike.
8. Produce the first correct two-node shared inference with explicit correctness and failure evidence.
9. Add the first machine-readable placement/scheduler decision from real node profiles and measured topology.
10. Re-evaluate G0/G1 and only then widen the runtime/message surface.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
