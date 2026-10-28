# ComputeMesh code map — public runtime and clients

**Source:** public `main`, inspected 2026-10-28. **Status:** architecture/navigation guidance, not production-release approval. For current product readiness consult [CURRENT_STATUS.md](CURRENT_STATUS.md). For code ownership and release gates use the private master plan where authorized.

## Where developers start

| Task | Source of truth | First verification |
| --- | --- | --- |
| Public REST APIs, auth boundary and user requests | `services/gateway/` | API contract and gateway tests |
| Distributed jobs, reservations, signed plans and execution | `services/orchestrator/` | orchestrator/placement/retry tests |
| Wire formats, public message schemas and signed envelopes | `protocol/` | schema / message compatibility tests |
| Public research/reference scheduling | `services/scheduler/` | explicit reference tests, **not** private production scoring |
| Provider agent and local hardware nodes | `apps/node/` | enrollment, heartbeat, reconnect tests |
| Local NodeOS diagnosis | `services/appliance_dashboard/` | dashboard auth/security tests |
| Bootable miner image creation | `tools/appliance/` and `deploy/appliance/` | immutable provenance, BIOS/UEFI and physical hardware receipts |
| Inference engine bindings and distributed RPC experiment | `runtime/llama/`, `runtime/cuda/`, `runtime/network/` | pinned binary, CUDA/Vulkan and physical tests |
| Website/public catalog and administration UI | `portal/` | route, link, API, auth and mobile-browser tests |
| Packaged Android client | `apps/android/` | Gradle, QR pairing, signed package/device tests |
| Windows provider/runtime setup | `setup/`, `deploy/windows/` | installer, NTFS, token/identity, update/rollback tests |
| Dedicated desktop end-user experience | `apps/desktop/` | **planned**; do not conflate with existing provider installer |
| Model inventory and package manifests | `models/`, `protocol/schemas/` | model hash and schema checks |
| CI / build / deployment | `.github/workflows/`, `deploy/` | protected, signed version and test/approval receipts |
| Unit/integration/e2e evidence | `tests/`, component tests | exact commands, source SHA, reproducible receipt |

## Runtime boundaries

The public repository contains client, node, inference, protocol and reference control-plane implementations. Production placement, private model/score, reputation, fraud and pricing data are not owned here. The private ControlPlane supplies a bounded signed placement response, which the public executor validates. Never put private production keys, fleet secrets or unreleased business policy in this repository.

## Frontend copy warning — verified 2026-10-28

Public `portal/webui` has 93 tracked files. `apps/android/app/src/main/assets/webui` has 72. Of 68 overlapping relative paths, 67 have identical Git-Blob SHA; the remaining shared path is `_app/immutable/bundle.Z__83NAY.js`. Many files exist only in one of these trees because they are built or platform-packaged artifacts. **No automatic deletion or blind copy is permitted.**

The private `ComputeMesh-ControlPlane/portal_inetconnector` currently mirrors 160 public `portal` relative paths: 106 exact SHA matches and 54 differ; the public side adds another 21 paths. The actual webroot/host source and any legitimate site-specific overrides need a reviewed migration, including legal URLs and cache assets. This is not a proof of production parity.

## Naming and ownership rules

1. Keep HTTP/web handlers thin. Protocol schemas and service boundaries own contracts; no local JS inventing its own authorization logic.
2. Separate provider/node controls from end-user application workflows and private operator placement.
3. Use one pinned llama.cpp build for verified experimental CUDA/Vulkan RPC compatibility. RPC is **opt-in only**, must not be publicly exposed and needs authenticated transport.
4. Generated frontend and installer outputs must have a traceable source commit, version and checksums. Do not hand-edit bundles, APKs or release JSON signatures.
5. Imports and command launch paths are public contracts. Before moving files, enumerate imports, dynamic entry points, systemd services, batch scripts, Android Gradle assets, Plesk routes and tests. Add a tested compatibility layer where needed.
6. A duplicated filename does not establish redundant behavior. Diff and classify each candidate; retain explicit evidence.
7. Use narrow changes with tests and release receipts; never use folder cleanup to bypass a security or integration gate.

## Required migration order

- Document authoritative entry points and dependency graph.
- Reconcile the dual website trees and immutable release/deployment pipeline.
- Normalize WebUI build to Android packaging with explicit fingerprint and generated-asset policy.
- Consolidate obsolete launchers and imports one module at a time under CI.
- Complete hardware, Windows native security, Android device, signature and Kimi two-host evidence **before** `RELEASE_GO`.

Current project status remains **`RELEASE_NO_GO`**. Historical plans may document past successes; do not infer present production behavior without current source/build/device receipts.
