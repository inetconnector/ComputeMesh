# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, durable orchestration, protocol/session foundations, lab/runtime measurement tooling, Windows/Linux lab UX, and first real Windows↔Linux target evidence  
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
- real target-machine smoke/fix pass: branch `fix/real-target-lab-setup`, prepared from the 2026-08-21 Windows + `supersrv-trixie` run

## What exists

- synchronized English/German root READMEs;
- architecture/protocol/security/benchmark/failure/privacy/data-model documentation and ADR process;
- Draft 2020-12 machine-readable contracts;
- node inventory, TCP network, and llama-bench measurement tooling;
- deterministic Job/Reservation state semantics;
- transactional SQLite reference persistence with durable idempotency, revisions, leases, restart recovery, request fingerprints, schema migration, and atomic reservation → job/stage binding;
- transport-neutral control envelope, structured errors, and first durable handlers (`ReserveCapacity`, `CommitReservation`, `CancelJob`);
- authentication-gated node-session state machine with a mandatory injected verifier boundary and no permissive default;
- Windows M0 Lab Setup with `SETUP.cmd` and direct `.cmd` role launchers;
- Linux M0 Lab Setup with root `setup.sh`, direct `.sh` launchers, package-manager support, private-interface/firewall handling, and official llama.cpp Linux asset selection.

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

Previously verified benchmark blocks:

- inventory tests: 3/3;
- TCP network benchmark tests: 4/4;
- llama-bench adapter tests: 6/6;
- loopback network result and converted llama-bench fixture results validate against benchmark-result schema.

Control/session evidence:

- control/orchestrator handler + persistence regression workspace: 37/37;
- protocol envelope/payload/schema/node-session suite: 29/29;
- node-session-specific portion: 14/14.

Previously verified shared/Windows setup evidence:

- `setup/lab.py` unit tests: 7/7;
- Windows script invariant/static tests: 5/5;
- prior combined setup tests: 12/12;
- synthetic helper smoke flow inventory → network-client → llama-adapter → persisted config: passed.

New Linux setup evidence:

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
- Windows direct `setup/TESTS.cmd`: passed 13 benchmark tests, 34 orchestrator tests, 29 protocol tests, 19 setup tests, with 6 Linux-specific tests skipped on Windows because Bash is unavailable there.
- Windows direct `setup/NODE.cmd`: passed and captured profile at `artifacts/lab/lab-d6332cbe/20260821-133030Z-inventory`.
- Linux direct `setup/TESTS.sh` on `supersrv-trixie`: passed 13 benchmark tests, 34 orchestrator tests, 29 protocol tests, and 19 setup tests.
- Linux direct `setup/NODE.sh` on `supersrv-trixie`: passed and captured profile at `/root/ComputeMesh/artifacts/lab/lab-144a13f1/20260821-133107Z-inventory`.
- Real Windows -> internet Linux TCP benchmark, source-limited by temporary `ufw` rule from `92.117.115.62` to `89.58.11.237:43191`, then rule removed: RTT p50 11.884 ms, RTT p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s. Local artifact: `artifacts/lab/lab-d6332cbe/20260821-133137Z-network`.
- Real Windows CUDA llama.cpp benchmark using `qwen2.5-coder-7b-instruct-q4_k_m.gguf` and existing llama.cpp b9987 CUDA build: prefill 2866.127 tokens/s for 512 prompt tokens; decode 76.210 tokens/s for 128 generated tokens; backend CUDA; artifact `artifacts/lab/lab-d6332cbe/20260821-133336Z-llama`.
- Real Linux CPU llama.cpp smoke using official downloaded llama.cpp b10549 CPU build plus copied `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tokens/s for 128 prompt tokens; decode 0.201 tokens/s for 32 generated tokens; backend CPU; server artifact `/root/ComputeMesh/artifacts/lab/lab-144a13f1/20260821-134100Z-llama-cpu-smoke`, mirrored locally below `artifacts/lab/server-supersrv-trixie/`.

**Evidence boundary:** this is real Windows↔Linux target evidence, but not a trusted private-LAN two-computer test. The server is on the public internet and has only a public `eth0` plus Docker private bridge addresses, so the assisted LAN setup cannot use it as a normal private LAN peer. The public network measurement was intentionally run through the engineering CLI with a temporary source-limited firewall rule, not through the unauthenticated LAN UI flow. No distributed shared inference exists yet.

## What does not exist / is not yet evidenced

- trusted private-LAN A↔B results using the assisted LAN UI;
- production provider-node application/service/installer;
- distributed runtime/shared inference;
- Gateway/API/scheduler;
- production orchestrator service/database;
- production node credential verifier/enrollment/key lifecycle;
- full NodeHello/Auth/Profile wire binding and remaining runtime/artifact handlers;
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

Neither the Lab Setup nor the session skeleton accepts ADR 0002/0005 by implication.

## Next actions in order

1. On two real target machines, use `SETUP.cmd` on Windows or `./setup.sh` on Linux.
2. Choose **Prepare this computer** on both and retain both profiles.
3. Run network server/client A→B and B→A on a trusted LAN, including mixed Windows/Linux if that matches the target environment.
4. Run the llama.cpp benchmark workflow on each relevant machine with the selected GGUF.
5. Compare measured memory, RTT/throughput, prefill/decode, and choose the exact M1 two-node spike.
6. Specify/implement the concrete ADR-0005 credential verification path without weakening the no-default verifier boundary.
7. Bind NodeHello/NodeAuthenticate/Capability/Profile/Benchmark wire payloads to the session skeleton.
8. Execute the llama.cpp-oriented ADR-0002 runtime spike behind the ComputeMesh boundary.
9. Add activation-payload-size and controlled latency/jitter/loss experiments.
10. Produce the first correct two-node shared inference and begin scheduler calibration.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
