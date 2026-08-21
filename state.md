# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, durable orchestration, protocol/session foundations, lab/runtime measurement tooling, and Windows/Linux lab UX  
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
- generated local `LD_LIBRARY_PATH` wrapper and `llama-bench --version` acceptance check;
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

**Evidence boundary:** the Linux shell/UX has now been executed on Linux, but not yet against two real target machines or a real downloaded target GGUF/llama.cpp run. The Windows PowerShell/CMD layer remains statically tested rather than end-to-end executed in the development environment.

## What does not exist / is not yet evidenced

- real target-machine A↔B LAN results (Windows, Linux, or mixed);
- real target-lab llama.cpp prefill/decode results;
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
