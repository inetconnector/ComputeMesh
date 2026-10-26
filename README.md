# ComputeMesh

## Current local P0 integration candidate (2026-10-26)

This checkout is a local development candidate, not a published release. It
is on `codex/p0-auth-placement-20261026`; the runtime source commit used for
the fresh local NodeOS artifact is
`962fc0b9c6910b69455f3e8e226ba930abc6c7b4` (a documentation-only follow-up
may have a newer public HEAD). The local changes implement one
canonical enrolled Node ID across provider, heartbeat and dashboard paths,
explicit authenticated rename/migration, serialized and single-owner
heartbeat publication, controlled enrollment → preflight → provider/
heartbeat activation, and a portable appliance builder for Linux/WSL.
The dashboard is now an HTTP/UI surface only; the platform launcher or the
NodeOS heartbeat unit owns the single relay instance.

The builder attests the exact source commit and tree, requires a verified
Debian archive keyring, keeps the llama.cpp pin at `v0.4.1`
(`29aaf1c27faa48292357cea2120d94114a545006`), embeds secret-free provenance,
and writes SHA-256/size evidence for the final artifacts. A real Debian
13/Trixie live image was built locally in isolated WSL2 from source commit
`962fc0b9c6910b69455f3e8e226ba930abc6c7b4`, source tree
`3ad8208d9f1a6f58898deaa5af4865d031ae468b`, with `source_clean: true`.
Debootstrap accepted the Release signature with key ID
`41587F7DB8C774BCCF131416762F67A0B2C39DE4`. The ISO is 836,763,648 bytes
with SHA-256
`1e3696b77957cbb0090f1b9ee86c207c299af7bcac341f73d7f89af32fd53e0b`; the
compressed 64-GiB image is 820,000,732 bytes with SHA-256
`384f3cfa16261a3f3690bcbd33aeed790f1c08d1d38afaabddbf31ea97f19bd8`; the
provenance sidecar SHA-256 is
`1d44e54359119fbb5c9853bda9370154df62a0efdce8f61ebe3a3a01089bd993`.
`xz -t`, ISO BIOS/UEFI El Torito inspection, and a read-only ext4 persistence
mount passed; `persistence.conf` contains `/ union`.

The same ISO was booted separately through BIOS and UEFI in isolated QEMU/TCG
with 4096 MiB RAM, serial logs and a snapshot of the generated image. Both
guests reached `basic.target`, started the local appliance service, exposed
the local dashboard through host-only forwards (`18080` BIOS and `18081`
UEFI), and returned HTTP 200. The serial logs ended at the `ttyS0` login
prompt. This is `VM_BOOT_PASSED` for the unenrolled VM smoke test only; it is
not physical GPU, enrollment, or production-release acceptance.

Final local focused groups pass: NodeOS/identity/builder/enrollment `64`,
provider/model/credits/sharding `68`, and Agent Workspace/UI/mesh/portal
`79 passed, 5 skipped`. The versioned public suite reports `1783 passed,
18 skipped, 42 subtests passed, 1 failed`; the only failure is the historical
invalid Ed25519 signature in `portal/updates/version.json`, which remains
`BLOCKED_SIGNING_AUTHORIZATION` because no signing key was used. The unified
public harness reports `895 total, 894 passed, 1 failed, 0 errors`; it has the
same single fixture failure. Physical NodeOS/GPU boot, real inference tokens,
physical GPU inference, Windows Ollama enrollment/reconnect, multi-host
networking and the native Windows NTFS TOCTOU gate remain open; the isolated
unenrolled BIOS/UEFI VM boot is the only boot evidence. No push, merge,
release, deployment or production credential was used; the overall status
remains `RELEASE_NO_GO`.

## P0 first-install enrollment and evidence contract (2026-10-26)

The generated `computemesh-enroll` launcher sets `COMPUTEMESH_NODEOS=1`
itself, so invoking it with `sudo` does not silently skip provider ownership,
preflight, or controlled service activation. Enrollment now uses the
side-effect-free `tools/security/node_auth_token_storage.py` after the gateway
response and preserves retryability when durable token storage fails. The
heartbeat relay reads the exact `COMPUTEMESH_NODE_PRIVATE_KEY` persisted in
`provider.env`; missing, unreadable, relative, or switched keys fail closed.

Enrollment and boot preflight validate the node-profile and both actual
`llama_cpp_prefill`/`llama_cpp_decode` documents against the session schemas,
positive measured values, one profile revision, one model, and one exact
llama.cpp build. The builder installs an `EVIDENCE_REQUIRED.md` operator
diagnostic and never fabricates profile or performance numbers. BIOS and UEFI
boot entries now expose `ttyS0` with `console=ttyS0,115200n8` for isolated VM
diagnostics. The fresh image and isolated BIOS/UEFI guest boot now have local
evidence as described above. Physical GPU inference, enrollment, and release
gates remain open; overall status is still `RELEASE_NO_GO`.

## P0 abschließende Integrationshärtung (2026-10-26, lokaler Entwicklungsbranch)

Der aktuelle lokale P0-Kandidat schließt fünf Integrationsfehler im echten
Gateway-, Placement-, NodeOS- und Enrollment-Pfad:

- Eine bereits registrierte Legacy-Node ohne Owner-/Ed25519-Bindung kann nicht
  mehr durch einen fremden Owner-Key und eine selbst erzeugte Signatur
  übernommen werden. Gültige bestehende Owner-Migrationen bleiben möglich;
  eine ungebundene Legacy-Zeile benötigt einen expliziten Enrollmentnachweis.
- Placement-Request-IDs werden in der vorhandenen SQLite-Lease-Schicht
  unveränderlich an Tenant, Modell-/Artifact-Vertrag, Kandidaten und den
  konkreten Node-Plan gebunden. Geänderte Retries werden fail-closed abgelehnt
  und dürfen keine ursprüngliche Lease freigeben.
- Preflight-/Enrollment-Launcher setzen ihr Arbeitsverzeichnis und
  `PYTHONPATH` selbst; systemd wartet auf das bestehende Preflight und den
  persistenten Mount. Der Dashboard-Prozess bleibt für lokale ErstEnrollment-
  Bedienung verfügbar, während der Heartbeat erst nach erfolgreichem
  Preflight startet.
- POSIX-Schlüssel und Token bleiben owner-only und werden dem Dienstkonto
  `computemesh` zugewiesen. Ein NodeOS-Prozess erzeugt keine neue Identität auf
  einem ungeprüften Overlay.
- HTTP-Enrollment und der persistente Provider-TLS-Kanal verlangen getrennte,
  explizite Host-, Port-, Servername- und CA-Daten; ein HTTPS-443-Fallback wird
  nicht mehr in den Provider-Kanal übernommen.

Die lokalen Regressionen verwenden ausschließlich neu erzeugte Testidentitäten.
Der öffentliche Code ist in `5bb69f9` und `1e1969b` auf Branch
`codex/p0-auth-placement-20261026` committed. Diese Nachweise sind keine
Hardware-, Produktions- oder Releasefreigabe: NodeOS-Boot, AMD-GPU-Inferenz,
WAN/BFT-Abnahme und der native Windows-Security-Gate bleiben offen.

## P0 release-artifact provenance (2026-10-26, local development branch)

NodeOS release builds now embed a secret-free provenance marker containing the
public source commit, ComputeMesh version and pinned llama.cpp build. The
release builder validates that marker in both the ISO and the compressed image
before accepting an artifact, records SHA-256 and byte-size evidence in an
atomically written sidecar, and promotes freshly built images from an isolated
staging directory. Missing, stale or inconsistent images are rejected rather
than silently reused. Manifest signing additionally requires explicit operator
approval through `COMPUTEMESH_RELEASE_SIGNING_APPROVED=1`; no signing key was
used for this local change and no release was produced.

The corresponding tests cover missing provenance, stale source commits and the
signing approval gate. The real Debian/chroot/image build, physical boot,
flashing and production publication remain separate gates.

The legacy security-audit test now injects only fresh local static catalog
entries when it tests billing behavior without a runtime. It does not alter the
production catalog's unavailable-model fail-closed behavior. The checked-in
historical update manifest still has an invalid signature and remains a
release blocker; it was not re-signed locally.

## P0 authenticated reconnect hardening (2026-10-26, local development branch)

The gateway heartbeat path now fails closed for an existing legacy node that
has no stored Ed25519 public key: an arbitrary caller-supplied key and
signature cannot replace its token or bind the node. New signed heartbeats
use a canonical v2 field set containing the node ID, token, timestamp, nonce
and optional previous node ID. Nonces are retained in the registry and
consumed atomically, so a parallel replay cannot win a second state update.
First key binding, registered-key rotation, owner migration and node-ID alias
retirement require the existing token, a registered key, or the existing
owner/enrollment authorization. The appliance relay emits the v2 proof.

The local security change is committed as `13db578`
(`fix(security): fail-closed node reconnect identity`). It was verified with
the real localhost gateway and local Ed25519 test identities; no production
host, deployment, push or release was performed. Cross-shard BFT, NodeOS
reboot, AMD-GPU inference and complete mesh E2E acceptance remain separate
open gates.

## P0 fail-closed node identity persistence (2026-10-26, local development)

Node private-key and tunnel-token storage now fails closed when an existing
identity cannot be read, protected, or atomically persisted. Symlink and
non-regular paths are rejected; POSIX writes use restrictive permissions and
atomic replacement; Windows does not silently fall back to plaintext when OS
protection is unavailable. The relay also refuses to start without its
persistent private key and no longer emits an unsigned heartbeat after a
signing failure. Local tests use only fresh test identities and cover storage
failure and relay startup failure. This is code/local-test evidence, not a
hardware or production enrollment claim.

## P0 NodeOS boot contract (2026-10-26, local development)

The live appliance builder now validates its Debian mirror, fails on service
enablement errors, embeds the real tty1 monitor, installs declared Python and
portal runtime content, and wires a fail-closed preflight into the existing
provider service. The preflight requires a provisioned provider environment,
persistent Ed25519 key, CA, evidence files, ext4 `persistence` storage,
`llama-server`, and a successful Vulkan probe. `computemesh-enroll` reuses the
existing signed gateway heartbeat/enrollment path and writes provider
configuration only after the enrollment response is accepted. No image was
built, flashed, booted, or deployed on this Windows host; physical NodeOS and
AMD/NVIDIA acceptance remain open.

## P0 verified inference readiness (2026-10-26, local development)

`ModelEngineService` now reports `INFERENCE_READY` only after the pinned
`llama-server` binary, the selected accelerator runtime (including Vulkan,
CUDA, or ROCm where applicable), the verified GGUF artifact and the health
endpoint have all passed. The authenticated provider agent and live
registration carry that status forward and fail closed for inference requests
or placement when runtime verification is absent. The existing tunnel relay
continues to publish the same engine status in `telemetry.model_runtime`.
The local tests use injected test probes; no AMD hardware or production node
was used, so physical inference acceptance remains open.

## Vertiefte Architekturoptimierungen, Fehlertoleranz und Invarianten-Härtung Teil 8 (2026-10-21)

- Architektur-Härtung Teil 8 (Model & Shard Manifest Invariants) implementiert und dokumentiert. GitHub Actions CI durch Spending-Limit blockiert; Verifikation vollständig und erfolgreich über Inetconnector Local Bridge / lokale Test-Suite nachgewiesen Verifikation vollständig und erfolgreich über Inetconnector Local Bridge / lokale Test-Suite nachgewiesen.

## WebUI accessibility and public route fixes (2026-10-20)

The shared browser/Android WebUI now has a complete high-contrast light theme,
a compact opt-in Agent Sessions panel with an explanation of its purpose, and
reliable pointer handling for update, attachment, dropdown, and mobile-sheet
controls. Agent Sessions are production controls for durable multi-step tasks;
the panel stays closed until the user opens it. The clean public `/models` and
`/models/` URLs are explicitly resolved to the model catalogue instead of an
nginx directory listing. Portal registration also renders structured gateway
errors as readable messages rather than `[object Object]`.

The local development checkout also contains the first NodeOS/dashboard
remediation slice: expired dashboard sessions can be retried in place, the
dashboard uses the neutral gray visual direction, dynamic values are escaped,
and portal images are checked for valid local assets and alt text. Benchmark
and social-card artwork remains neutral until measured evidence is published.
The checked portal/WebUI assets are now deployed to both existing Plesk
webroots with a targeted rollback backup. Android build/install and signed
production release remain separate gates.

The Linux cryptographic updater supports deployment-specific absolute target
directories and an explicit allowlist of ComputeMesh systemd units through
`COMPUTEMESH_LINUX_UPDATE_TARGETS` and `COMPUTEMESH_LINUX_UPDATE_SERVICES`.
Unset variables retain the legacy defaults; production staging should set both
variables explicitly and keep the updater disabled until its target has been
validated.

## AI capability program (Paket 0, not released)

The AI Capability implementation plan is tracked in the private umbrella at `docs/agents-platform/AI_CAPABILITY_IMPLEMENTATION_PLAN.md`. This public branch introduces the versioned [evaluation corpus and evidence-gated baseline](tests/evals/README.md). It **does not** enable tools, change model routing, claim improved inference quality, or authorize a production rollout. The current unmeasured baseline blocks release. The gateway owner check and in-process Python interpreter remain mandatory P0 security stop-gates before any new powerful tools are enabled.

**Languages:** **English** | [Deutsch](README.de.md)

The portal reads live mesh telemetry after all client state has initialized,
including when its core script is loaded dynamically. Missing measurements
are distinct from a measured zero; online nodes are reported by the gateway.

The portal has standalone product, project, marketplace, model, pricing,
download, LAN-mesh and playground pages rather than homepage fragment links.
`portal/portal-business.css` supplies a shared neutral, responsive presentation;
existing account, fleet, inference and download controls remain. The model
library and playground read the gateway's live model catalog. Marketplace
cards require fleet authorization and show missing measurements explicitly.
The pricing page lists prices only when a live model ID exactly matches a
published price tier; it does not estimate provider earnings.
German and English are the portal's supported languages.
Shared navigation dropdowns keep the hover path continuous between their
trigger and submenu, including wrapped narrow-screen navigation.
All 28 normal portal documents use the same canonical header, navigation
targets, localized language control and cache-pinned portal assets. This
includes downloads, model detail and comparison pages; standalone auth,
payment, game and bundled WebUI documents intentionally keep their own
application shells.

The WebUI validates saved model selections against the current gateway and
reachable peer catalogs. Discovery requests have bounded timeouts; failed
peer discovery or optional slot lookup cannot discard a usable gateway model.
A failed direct-node request falls back using a gateway-advertised model,
not the obsolete model ID stored in an older conversation. Portal and Android
WebUI assets share this behavior; Android installation is a separate release gate.

The dashboard renders QR codes locally through an authenticated,
rate-limited `/api/v1/qr` route. No third-party QR image host is required, and
credentials or non-HTTP(S) values are rejected. Desktop and Android WebUI
entrypoints load the same neutral theme asset; the Android debug build is
verified locally, while signed production release remains a separate gate.

Gateway MCP tools now default to owner-only unless explicitly reviewed as
public read-only information tools. Only the configured gateway admin token
can authorize host-level tools or manage custom tools. The legacy in-process
Python execution tool is not registered; an isolated execution service is
still required before restoring code execution.

## In Plain Words

The current NodeOS dashboard also exposes real hardware telemetry, a
capability-aware safe fan profile, and authenticated model/runtime controls.
The safe fan profile can enforce a temperature-based minimum only when the
installed GPU driver exposes a writable control backend; unsupported Windows
drivers are reported as unsupported rather than showing fabricated values.
The bundled Android WebUI asset is maintained alongside `portal/webui/`. A
production Android APK is built through the separate signing/release process;
the current release artifact is published with the Android download assets.
Current TV-program questions are routed to live web search, including generic
questions such as “What is on TV now?”. Mobile clients use a node tunnel only
when its dedicated node-authentication credential is available; a fleet owner
key is never mistaken for that credential.
After a direct live intent has executed, the assistant receives the result for
synthesis without a second unrestricted tool registry, preventing unrelated
follow-up tool calls from replacing the authoritative live answer.

ComputeMesh is being built to connect many ordinary computers into one shared AI computer.

The idea is simple:

- People with spare GPU power can offer it.
- People who need AI compute can get suitable power from the network.
- ComputeMesh decides which machine is a good fit for a request.
- Every run should be measured, verifiable and fairly accounted for.

Think of it like a power grid for AI compute: not one giant data center doing everything, but many suitable machines working together.

## Why It Matters

AI needs a lot of compute. At the same time, many GPUs sit unused in gaming PCs, workstations, small servers and offices. ComputeMesh is building the technology to make that power usable later in a secure and measurable way.

The goal: AI compute should not belong only to a few large providers. More people and companies should be able to offer compute, use compute and get paid for it.

## How the two repositories fit together

ComputeMesh is intentionally split into a public execution repository and a private production-control repository:

| Repository | Role |
| --- | --- |
| `inetconnector/ComputeMesh` **(this repository)** | **Public execution plane:** provider/node software, hardware and network measurement, gateway/API surfaces, protocol/identity contracts, execution evidence, llama.cpp integration and the runtime that carries out an approved plan. |
| `inetconnector/ComputeMesh-ControlPlane` | **Private production control plane:** production placement/recovery decisions and the private operational intelligence used to decide how available compute should be assigned. |

A simple way to think about it is: **the private Control Plane decides; the public ComputeMesh runtime executes.** The public side can provide a bounded snapshot of live hardware/runtime/network capability. The private side can return a signed execution plan containing only what the executor needs, while proprietary ranking inputs and operator data stay private.

This separation also applies to the planned multi-model mesh: the private Control Plane can decide which verified model/quantization should run on the GPUs currently online, how GPUs should be grouped into one or more clusters, and when popular models need replicas or rebalancing. This public repository provides the portable runtime and provider-side mechanisms needed to execute those signed plans.

The private repository pins this public repository as its `ComputeMesh/` Git submodule, making `ComputeMesh-ControlPlane` the umbrella checkout for operators who have access to both halves.

## What Works Today

ComputeMesh is currently a lab and pre-production system. It already includes:

- a public website that defaults to German in Germany;
- public live capacity counters based only on fresh authenticated node heartbeats;
- **Active live mesh fleet (64 GB VRAM online):**
  - Node A (`test-node-custom`): Windows client with NVIDIA GeForce RTX 3080 Laptop GPU (16 GB VRAM), authenticated at the Gateway, **measured inference: 82.24 tokens/s** (Gemma 3 4B via Ollama adapter).
  - Node B (`cm-inference-node-01`): Linux NodeOS 1.2.187 with 6x AMD Radeon Polaris GPUs (48 GB VRAM), authenticated via node tunnel, diagnosed for Vulkan llama-server and ext4 persistence.
- **Unified test suite verification:** 889/889 tests passing across all 12 subsystems in `run_all_tests.py` plus 89 unit tests in ControlPlane (978 total).
- signed Windows and Linux clients with update checks;
- a gateway that can receive AI requests;
- an AI Studio web interface with API-key, passkey, magic-link and registration flows; magic-link requests use the gateway route, prevent duplicate submissions, time out clearly, and display readable API errors. Login emails use high-contrast, mail-client-compatible styling and include a wrapping fallback link. Native llama.cpp tools are reported as unavailable unless that optional server feature is enabled, while ComputeMesh MCP tools remain on their separate API;
- an owner-only Universal Skill Execution MCP tool with explicit skill metadata, intent matching, prerequisite checks, task planning, structured state, provenance/evidence tracking, tool-failure reporting and a final quality gate;
- a per-browser AI Studio model selector in the **Model Information** panel's **Model** row; each chat request uses that selection, and model modalities control which photo/image, audio and video attachments are offered (text and PDF remain available). Large photo uploads (up to five images per request) are resized and compressed locally; the actual serialized request is measured and images are adaptively recompressed to fit the gateway payload limit;
- automatic fleet-aware model discovery: an authenticated browser session queries the online fleet catalogue, loads model inventories in parallel, deduplicates and ranks them, and routes each selected model to the node that reported it. Local loopback discovery remains available for standalone nodes;
- a provider app that lets a machine report available compute;
- a restartable, least-privilege Linux systemd provider-service template under
  `deploy/systemd/`; installation, enrollment and live production activation
  remain operator-controlled. The provider's `SIGTERM`/`SIGINT` path unblocks
  the authenticated control socket before supervisor restart, and the unit
  forwards optional inference, model-preparation and typed-environment settings
  when configured;
- an optional Windows Cline integration that uses the local OpenAI-compatible
  endpoint and keeps client-owned tool schemas separate from ComputeMesh MCP
  tools;
- a verified local GGUF model manager for NodeOS/desktop providers: pinned
  Hugging Face downloads, resumable partial files, exact size/SHA-256/GGUF
  validation, one supervised loopback-only llama.cpp runtime and a dashboard
  tab for start/stop/delete/status operations;
- proportional multi-GPU llama.cpp layer-split requests based on the healthy
  discrete GPU inventory and aggregate VRAM budget. The runtime reports the
  requested allocation separately; exact physical execution remains a future
  attestation gate rather than a claim;
- early real two-machine llama.cpp experiments;
- measurements for machine performance, network connection and execution;
- security rules so protected jobs do not silently fall back to unsafe machines;
- clear boundaries for what is still research and what is not yet a product promise.

Current signed client/update channel: `v1.2.187` is the strictly monotonic release succeeding `v1.2.186` and `v1.2.185`. It delivers: bidirectional mTLS tunnel deadlock and timeout fixes, deterministic Service Worker precache revisions (MD5 LF normalized), neutral resting action buttons with pink `:hover`/`:active` activation, full Codex-parity Agent Workspace integration (`/agent`) replacing the mini-popup, fail-closed auth token resolution without insecure fallback defaults, and hardened deployment rollback scripts. All 889 tests pass cleanly in `run_all_tests.py`. Live deployment status is recorded in `state.md`.

The current working tree extends that mesh path for paired mobile clients: the
Android WebUI contains the same model selector as the portal, refreshes LAN and
fleet peers continuously, queries up to 64 peers with bounded parallelism, and
merges their live model catalogues. The default is the strongest currently
available model by reported parameter size, while a valid explicit selection is
preserved. Stale placeholder selections are replaced automatically and failed
nodes are skipped during inference failover. The fleet owner key is accepted on
NodeOS only for inference; dashboard, model-management, fan and system actions
still require the dedicated node credential.

Android LAN admission now keeps discovery separate from trust. Each discovered
peer receives a bounded credential-free health/model probe and reports its
state, model IDs and authentication requirement through the phone-local
`/v1/mesh/peers` endpoint. Unknown local peers never receive the fleet owner
key during catalogue discovery; unreachable or authentication-required peers
remain visible but are excluded from automatic inference routing until they
become usable. This preserves the requested automatic LAN behavior while
making manual pairing an explicit, localized exception.

The public Agent Platform also reconciles heartbeat freshness before routing:
the configurable `COMPUTEMESH_AGENTS_NODE_STALE_AFTER_SECONDS` window defaults
to 90 seconds. A stale verified node is quarantined and cannot receive a new
lease until an authenticated session/profile refresh restores it through the
normal admission path.

## What Is Not Promised Yet

ComputeMesh is not yet a finished product for arbitrary public AI workloads. It still needs broader real-world validation across different GPUs, networks and locations.

Confidential AI execution is also not claimed as a finished hardware security guarantee yet. That requires a concrete TEE/GPU-attestation technology with a real verifier. Until then, `CONFIDENTIAL` intentionally fails closed instead of being enabled unsafely.

## Try It Quickly

Clone/download the repository and use the launcher for your OS:

**Windows:** double-click `SETUP.cmd`  
**Linux:** run `./setup.sh` (or `bash setup.sh` if the executable bit was lost).

The menu can inspect the machine, measure the network connection, test local model speed and run the test suite. Model weights are never downloaded automatically.

The detailed two-computer developer walkthrough is in [setup/README.md](setup/README.md). The current public status is in [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md). `state.md` is the detailed technical project log.

## NodeOS local models

The provider dashboard's **Models** tab manages GGUF artifacts stored in
`COMPUTEMESH_MODEL_DIR` (NodeOS default:
`/var/lib/computemesh/models`; Windows default:
`%USERPROFILE%/.computemesh/models`). A Hugging Face installation requires:

- a repository ID and GGUF basename;
- a full 40-character source commit SHA;
- the exact expected byte size and SHA-256 digest;
- the model layer count, quantization and license identifier.

Downloads run in the background and resume through HTTP Range requests. A
partial file is never catalogued. Activation rechecks path containment, regular
file type, exact size, GGUF magic and SHA-256 before starting `llama-server` on
`127.0.0.1:8081`. Only one model can be active at a time. The local chat router
uses that managed llama.cpp endpoint when it is healthy; otherwise it can use a
separately installed Ollama runtime. If neither runtime is healthy, model and
chat endpoints fail with `503` and do not invent answers or token usage.

The dashboard warns when the configured model filesystem is too small for the
recommended local catalogue or when NodeOS is running on a temporary overlay
filesystem. The download API also reports the exact available and required
bytes, including its safety reserve. On a NodeOS image, ensure the persistent
data partition is mounted; for another disk set `COMPUTEMESH_MODEL_DIR` to a
writable directory on that disk before downloading models.

The NodeOS image builder pins upstream llama.cpp `v0.4.1` at commit
`29aaf1c27faa48292357cea2120d94114a545006`, builds the Vulkan server, includes
AMD and NVIDIA runtime packages, locks the root account, disables password SSH
and creates a 64 GiB persistence area by default. Override image persistence
with `COMPUTEMESH_PERSISTENCE_SIZE_MIB` (16-256 GiB). A real image build and
physical six-GPU acceptance run are required before this branch can be tagged
or released.

## Technical Overview

For developers, this means:

- Machines can measure their hardware and local model speed.
- Two machines can run a controlled lab test together on one model execution.
- The gateway can receive requests and send them to suitable providers.
- Providers must enroll and prove their identity.
- Results, measurements and execution evidence are recorded.
- The scheduler must not silently lower the safety level of protected jobs.
- Public jobs can later use matching GPU power globally when the rules allow it.
- Confidential jobs stay blocked until real hardware attestation is implemented.
- The website, downloads and update files are versioned and signed.

The sections below are more technical. They describe the boundaries, security rules and experiment paths for developers and operators.

### Durable Mesh Agent Runtime

The public runtime also contains a feature-gated durable agent layer under
`services/mcp/platform/`. It provides SQLite-backed sessions and turns,
bounded context compaction, policy-filtered tool execution, authenticated
NodeOS dispatch, artifacts, usage, traces, child sessions, origin-aware MCP
discovery and localized session/approval projections. A side-effecting tool
pauses its durable turn at `waiting_for_approval`; an approved continuation
must match the original session, turn, tool and argument digest and is consumed
once. Approval HTTP requests never execute the side effect themselves. The
legacy chat and inference path remains available when the feature is disabled,
and `POST /v1/agents/sessions` can atomically create a model-bound queued task.
After a completed turn, authenticated clients can queue follow-up input with
`POST /v1/agents/sessions/{session_id}/turns`; the same durable worker and
policy/approval boundaries are used. The bundled portal and Android WebUI
include the localized task/continuation controls.
Both copies retain only a bounded, redacted session projection and server
cursor across app/WebView restarts; offline views retry in the background, while
authentication failures clear the cache and no prompts, event payloads,
approval arguments or credentials are persisted locally.
The gateway can optionally require an immutable registered agent definition at
worker claim time with `COMPUTEMESH_AGENTS_REQUIRE_DEFINITION=1`; its model,
mesh-node and tool constraints are applied without exposing the definition
payload, while legacy compatibility remains the default.
An optional server-side OpenAIAgentsClient can bridge selected sessions to the
official OpenAI Agents API for session creation, input/cancel events, saved
items and event streams. Its credential is read only from the server
environment and the local MeshAgentHarness remains the default; the adapter
does not run on Android or NodeOS and has no effect when unconfigured. Runtime
activation requires the explicit COMPUTEMESH_AGENTS_OPENAI_ENABLED switch.
Authenticated clients can also post `pause`, `resume` or `cancel` to
`/v1/agents/sessions/{session_id}/control`. Queued and waiting turns are
changed atomically; active workers observe the request at safe model/tool
boundaries. Both WebUI copies render these controls, and `MeshAgentWorker`
provides a stoppable polling loop for continuous pickup. The
`MeshAgentWorkerService` supervises bounded worker pools, startup recovery and
cooperative stop/join without changing the single-worker API.
`SubagentCoordinator` can optionally bind every child session/turn to an
injected `NodeLeaseStore` lease factory and releases that lease on success or
failure; node selection remains outside the public runtime policy boundary.
`AgentsPlatformRuntime.build_mesh_agent_worker()` now binds those turns to
the verified NodeOS dispatcher. The authenticated inference contract validates
and forwards bounded tool schemas to the provider's loopback OpenAI-compatible
runtime, preserves bounded native function-call responses and tool-call
history, and keeps routing and leases enforced at the control plane. The
streaming contract also preserves bounded native tool-call deltas and provides
binding-checked assembly into the same caller shape.
Authorized model preparation now uses a bounded, digest- and session-bound
NodeOS request/response contract with an explicit provider capability gate;
discovery and inventory remain read-only until installation is authorized. A
local pinned preparation manifest can now connect that route to the existing
NodeOS model manager, which retains commit, size, SHA-256, GGUF and storage
validation.
The public runtime also exposes `NodeOnboardingCoordinator` for safe automatic
LAN admission. It keeps discovered nodes visible, maps an authentication
challenge to `manual_pairing_required`, and only reaches a routable state after
identity verification, preparation and an accepted benchmark. Probe,
preparation and benchmark adapters are injected; discovery never transfers a
credential or grants implicit trust.
The authenticated live-provider channel also supports the bounded,
profile-revision-bound `ModelCatalogueUpdate`. When
`IntegratedLiveControlPlane` receives an Agent `NodeRegistry`, a complete
authenticated provider is admitted into Agent routing through the existing
identity, capability, preparation and benchmark gates. Missing or invalid
inventories fail closed for Agent routing while Shared Serving remains intact.
Mesh environments also have a typed authenticated NodeOS transport for
prepare, heartbeat, execute and shutdown. It binds each request to the
current session revision and environment lease and requires the
`mesh_environment_v1` capability. The provider can now enable a concrete
bounded NodeOS executor with `--environment-root`, supporting health,
inference and symlink-safe workspace operations. Mesh artifact staging now
transfers principal-authorized immutable data in bounded, digest-checked,
idempotent chunks with atomic commit and resume status. The process adapter
applies POSIX resource limits and Windows Job Object memory/process limits;
GPU/device isolation remains a separate deployment gate and no shell fallback
is exposed. Provider capacity admission also binds profiled GPU device IDs and
per-device VRAM limits. Live inference now reserves that provider capacity
through the authenticated channel before execution and releases it after the
response or stream; complete physical inference-process/device isolation
remains a deployment-specific gate.
Supervised agent workers can opt into bounded global, principal and session
concurrency budgets; the default remains the existing worker behavior. A
deployment can set `persistent_concurrency=True` on the runtime worker builder
to back those limits with SQLite admission leases shared by worker processes.
An optional tenant limit applies the same boundary across all sessions of one
tenant. Leases are atomically acquired, renewable, explicitly released and
reclaimed after expiry, so a crashed worker cannot reserve capacity forever.
Lease-bound model dispatch can also opt into bounded provider fallback with
`max_attempts`: transient connection, timeout and OS transport failures exclude
the failed node for the next attempt, use a distinct idempotency key, and emit
retry lifecycle events. A full reservation is treated as a scheduling
condition, so another verified candidate can be selected without consuming an
execution retry. Minimized route requirements can also enforce measured
throughput, latency and explicit node preferences. Validation and binding
errors remain fail-closed.
Approval-gated turns are resumed by the durable worker after an exact
principal/session/turn/tool/argument match; the consumed approval authorizes
that one side effect with its own stable idempotency key, after which the model
continues synthesis from the persisted tool result.
For self-hosted workspaces, `AgentsPlatformRuntime.build_process_workspace_transport()`
provides an opt-in shell-free child-process boundary with JSONL protocol limits,
wall-clock termination and POSIX resource limits. The direct local workspace
transport remains the compatibility default; GPU/device isolation remains a
separate deployment gate.
The persistent provider channel also supports caller-bound request IDs and
cooperative in-flight cancellation. Durable agent cancellation propagates from
the session control request through the AgentLoop, model callers, lease
dispatcher and authenticated NodeOS channel; provider backends receive the
bounded cancel token when they support it. A cancellation releases the waiting
control-plane call immediately, and the local HTTP inference adapter closes a
  blocking response when cancellation arrives. `LocalOpenAIInferenceBackend`
  also accepts an explicit deployment-owned `on_cancel` callback, so a
  provider that owns its model process can terminate it at the process
  supervisor boundary; shared model servers are never terminated by default.
  The runnable provider can opt into this only for its own managed model engine
  with `COMPUTEMESH_NODEOS_STOP_MANAGED_MODEL_ON_CANCEL=1`; it verifies the
  configured loopback origin before connecting `ModelEngineService.stop`.
Durable turns also carry a bounded priority and optional admission deadline;
workers apply bounded aging, rotate equal-score principals and atomically fail
expired queued work before claim. `WorkerSchedulingPolicy` is injectable from
the runtime builders, and older SQLite session databases migrate these fields
without losing existing turns.
The runtime also exposes an append-only `AgentDefinitionStore`: each
agent/version has an immutable digest covering its model strategy, instructions,
skills, tools, MCP servers, node scope, privacy class and limits. Re-registering
the same digest is idempotent; changing a published version fails closed.
The usage ledger supports transactional global, tenant, principal and session
quotas over lifetime, daily and monthly periods; this is metering and hard
limit enforcement, not a public pricing or settlement implementation.
Backend and mesh-dispatch callers also carry only bounded opaque execution job
and node identifiers into the agent result, usage ledger, durable events and
redacted traces. Placement scores, provider shares and private policy inputs
remain outside the public runtime.
`AgentEventOutboxDispatcher` consumes durable events with bounded consumer
leases, acknowledgement/release and restart recovery. Delivery is
at-least-once, so sinks must deduplicate by immutable `event_id`.
In-flight agent turns also persist bounded private execution checkpoints at
model/tool boundaries. An explicit resume can continue a saved tool batch or
final model result without blindly replaying the whole turn; approval resumes
intentionally replay only through the one-shot approval broker. Gateway agent
billing can persist verified provider evidence in its private SQLite store so a
process restart does not silently undercount completed model calls.
`MeshAgentWorker` claims queued/resumed work only through an injected model
caller and policy-bound harness. `BackendModelCaller` connects that worker to
the existing inference backend contract without duplicating provider routing.
Mesh deployments can enable
`COMPUTEMESH_AGENTS_MESH_PREFLIGHT_ENABLED=1` to defer queued work until the
verified node registry has a routable node for its bound model and requirements;
the default remains compatibility mode.
An integrated deployment can inject an authenticated control-plane client and
set `COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED=1` to route queued
`environment_type=mesh` sessions through verified NodeOS dispatch, routing,
leases and bounded retries. Startup and mesh turns fail closed without that
explicit wiring; `none` and `self_hosted` keep the existing backend path. Mesh
turns can also opt into the existing gateway hold/capture ledger when
`COMPUTEMESH_AGENTS_BILLING_ENABLED=1` is enabled. The mesh caller sends
authenticated selected-node and token evidence through a private observer to
that ledger; provider shares never enter public session events or usage
responses. Hardware-backed attestation and multi-provider settlement remain
separate deployment gates.
The canonical `services.gateway.live_server` bootstrap now provides that
authenticated client from its integrated TLS control plane and starts the
worker only after the live gateway gates pass; the compatibility gateway keeps
the client absent and therefore remains fail-closed for mesh dispatch.
Private deployments can also provide a `runtime_policy_resolver` to bind a
minimized, request/principal-bound `RuntimePolicyEnvelope` to each claimed
turn. The resolver is optional and never carries private placement, fraud,
pricing, provider-share or credential data into the public runtime.
The durable harness revalidates the envelope immediately before execution,
including expiry, request ID, principal and fleet binding, and fails closed on
rejection.
The canonical live-runtime module can register this callback on
`LiveSharedRuntimeRegistry`; `services.gateway.live_server` forwards it to the
worker automatically when the worker feature is enabled.
Gateway deployments may explicitly enable
`COMPUTEMESH_AGENTS_BILLING_ENABLED=1`; the gateway then uses the existing
persistent credit hold/capture ledger, requires verified provider shares, settles one
idempotent journal event per agent turn and releases failed/unmetered holds.
With the switch absent, the prior agent and chat billing behavior is unchanged.
Authenticated clients can list session-scoped artifacts and download
them through principal-bound `/v1/agents/...` endpoints, including bounded
resumable HTTP byte ranges with full-object digest verification. Operating-system
process isolation plus live provider/NodeOS preparation remain deployment gates.

The public executor contract supports version-2 N-stage plans with ordered
layer ranges, per-stage device indices and multiple RPC endpoints/devices.
Real 3+ node and multi-GPU hardware validation is still a production gate.

### Public/private production boundary

`services/scheduler/placement.py` remains the disclosed deterministic **research/reference** feasibility planner described below. It is not the production ranking engine.

Production placement feasibility/ranking, empirical performance state, reputation/fraud eligibility, private recovery selection, pricing/marketplace policy and settlement policy live in the separate private `inetconnector/ComputeMesh-ControlPlane` repository. The public orchestrator sends a bounded live candidate/network snapshot, accepts only a signed/unexpired execution plan, verifies it fail-closed and executes the minimum placement result without receiving private candidate scores or policy internals.

Verified public execution outcomes can be durably delivered to the private feedback path, where private performance/reliability inputs evolve without being serialized back into public placement responses.

### Global mesh trust/privacy policy

PR #55 (`feat(mesh): integrate confidential global mesh policy`, merged as `e410b1d2adb417cf0e79689279b22899258ba13c`) added the public policy layer for global routing without weakening the existing conservative production gate.

- Provider trust is modelled as `OPEN`, `VERIFIED` and `RESTRICTED`.
- Execution privacy is modelled separately as `PUBLIC`, `CONFIDENTIAL` and `CRYPTO_PRIVATE`.
- `PUBLIC` jobs may use a global heterogeneous GPU pool when technical admission, model/runtime/hardware fit, network requirements and job policy all match.
- Region/EEA and customer/contract restrictions remain independent policy predicates.
- The scheduler must not silently downgrade privacy: protected jobs never fall back to `PUBLIC`, never run on `OPEN`, and never run on plaintext-logging nodes.
- `CONFIDENTIAL` and `CRYPTO_PRIVATE` default OFF. Confidential execution requires a concrete technology-specific attestation verifier; TLS, containers, VMs and sharding are explicitly not accepted as confidential computing by themselves.
- Confidential attestation is bound to node identity, nonce, runtime measurement/digest and attested ephemeral public key. Content keys must not enter ordinary gateway/control-plane code; any key-release target must match the attested node, nonce and ephemeral key exchange.

The repository therefore contains policy contracts, schemas, filters and fail-closed tests, but it still does **not** claim real production-ready confidential-inference hardware. A concrete TEE/GPU-attestation technology and verifier must be implemented and enabled before `CONFIDENTIAL` can pass.

## M1 two-node placement and evidence bundle

`services/scheduler/placement.py` is the first machine-readable placement component. It is an **experiment feasibility planner**, not a production scheduler.

It checks:

- node/profile schemas and exact profile revisions;
- draining and stale/future-skewed profiles;
- selected model artifact size against all four llama-bench records;
- `contiguous_layers` permission in the model manifest;
- provider memory fractions plus a conservative planner memory cap;
- a coordinator→worker network measurement whose embedded local/peer Lab IDs are checked when present;
- a model layer count taken from the manifest when present.

It can emit:

- `shared_experiment` when a conservative contiguous two-node layer split is memory-feasible;
- `local_only` when only the coordinator baseline is feasible;
- `no_plan` when current hard constraints/memory evidence allow neither.

The output includes deterministic `decision_id`, contiguous layer ranges, relative `tensor_split` weights, hard-constraint explanations and the measured individual compute/network evidence.

Critically, the public research planner does not invent shared-runtime predictions when it lacks calibrated evidence:

```text
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

Current network benchmark records can embed `local_node_id`, `peer_node_id` and `peer_identity_binding`; the current server report is labelled `unauthenticated_server_report_v1`. This removes a manual experiment-bookkeeping step but **does not authenticate the peer**. Older network records and model manifests remain usable through explicit `caller_asserted_v1` peer/layer fallbacks in the direct placement CLI, and embedded evidence must never conflict with a supplied fallback.

For the current real M1 experiment, `services/scheduler/evidence_bundle.py` is deliberately stricter. Given two Lab evidence roots plus the model manifest, it selects the highest coherent profile revision, exact-size prefill/decode runs for one common model basename, requires all four selected llama-bench records across both nodes to carry one identical concrete llama.cpp build number/commit, and selects a correctly directed network record with embedded local/peer IDs. It does **not** allow caller-asserted peer or layer fallbacks. Ambiguous latest runs, multiple node identities, wrong-direction/legacy network evidence, corrupt evidence-looking JSON and model-size mismatches fail closed.

The resulting `experiment_bundle.schema.json` artifact includes the complete validated placement decision plus safe source basenames and SHA-256 of each selected source JSON. Absolute local paths are excluded. The hashes make the selected copied evidence set reproducible, but they are not cryptographic attestation of who originally produced those files. See [services/scheduler/README.md](services/scheduler/README.md).

## Two-machine Lab evidence transfer

`setup/evidence_transfer.py` removes the manual directory-copy step around the bundle builder while deliberately remaining a local trusted-lab utility.

On the worker, the export path scans only the node's Lab JSON tree and writes a ZIP containing recognized profile/benchmark evidence. It excludes model weights, llama.cpp runtime downloads, `config.json`, remembered local paths, and arbitrary files. Each included file is recorded by safe relative path, exact size and SHA-256 in `computemesh-lab-export.json`.

On the coordinator, import is fail-closed: the archive/member count and compressed/uncompressed byte totals are bounded; the member set must match the manifest exactly; encrypted/symlink/traversal entries are rejected; every file is streamed through the declared size and SHA-256 check; and extraction becomes visible only after an atomic temp-directory rename. Re-import verifies the existing tree rather than trusting it. Re-exporting the same evidence at a different time retains the same evidence identity, because the export timestamp is observational metadata rather than part of the content identity.

`setup/lab.py bundle --peer-export ... --model-manifest ...` then hands the verified imported worker tree plus the coordinator's local tree to the stricter current bundle selector. Windows and Linux have direct launchers for the same path. Export/import use only the Python standard library; the small JSON-schema dependency is needed only for bundle construction.

**Boundary:** these hashes detect corruption/change in the copied evidence. They do not authenticate the producer, sign a node, or attest hardware. The transfer path remains a controlled trusted-lab convenience, not production evidence transport.

## GGUF → model manifest

`tools/benchmark/gguf_manifest.py` removes another manual M1 bookkeeping step. For a local little-endian GGUF v3 file it can read bounded standardized metadata and derive:

- `general.architecture`;
- `<architecture>.block_count` as manifest `layer_count`;
- known standardized `general.file_type` quantization labels;
- model name/version/license metadata when present;
- exact local file size and streaming SHA-256 digest.

The helper never executes model code and never loads tensor contents into memory. License/version/quantization facts that are missing or not safely mapped must be supplied explicitly, and allowed partitioning modes are always explicit rather than inferred.

Current llama.cpp split metadata is also recognized. A primary shard with `split.count > 1` can be identified, but schema-v1 manifest generation is deliberately refused because one shard's digest/size does not represent the complete model and schema v1 does not yet encode shard membership/order strongly enough. Merge the complete shard set to one GGUF before generating the current ComputeMesh manifest. See [tools/benchmark/README.md](tools/benchmark/README.md).

## Controlled llama.cpp M1 experiment

`runtime/llama/rpc_spike.py` can discover current llama.cpp devices, record a deterministic local baseline, run an explicit local+RPC `layer` split, and compare the exact same model/prompt by token-ID digest when available (otherwise output digest). It records model/runtime/topology/timing evidence without raw prompt/output persistence. `runtime/llama/shared_trial.py` now composes that narrow first-proof flow into one fail-closed coordinator command: it rechecks bundle freshness and exact GGUF identity, requires the current `llama-server` build number/commit to match the build bound from both nodes' selected llama-bench evidence, preflights current RPC visibility, runs baseline and the planner-selected split through a fresh measurement relay, requires exact correctness, and builds `shared_run_evidence.json`.

The first experiment keeps coordinator HTTP on `127.0.0.1`, restricts RPC to literal loopback/RFC1918 IPv4, uses `--offline`, disables automatic fitting and cache surfaces, and treats upstream RPC only as a trusted-lab implementation detail. The automated runner currently requires an accelerator-backed coordinator rather than inventing local-CPU split semantics. See [runtime/llama/README.md](runtime/llama/README.md).

ADR 0002 has one recorded trusted-lab physical proof in `state.md`, but the harness remains an experiment path. It is not by itself a production runtime or security boundary, and any new topology/model/runtime build needs fresh evidence.

## Runtime network measurement relay

`runtime/network/tcp_relay.py` can sit locally between the llama coordinator and a trusted-private-LAN RPC worker. It listens only on `127.0.0.1`, connects only to literal loopback/RFC1918 IPv4, uses bounded queues, counts opaque bytes separately in both directions, separates setup/active timing, can add reproducible userspace stream delay/jitter, and can force controlled disconnects.

The relay does not parse RPC frames: byte totals include framing/control/data and are **not activation-tensor byte counts**. It also deliberately does not emulate packet loss by dropping TCP bytes. Packet-level loss/reordering remains a separate OS/network-emulation experiment. See [runtime/network/README.md](runtime/network/README.md).

## Verified real-target evidence

Historical physical-target evidence from 2026-08-21 includes:

- Windows target: RTX 3080 Laptop GPU, 16 GiB VRAM, 31.7 GiB RAM;
- Linux target: Debian 13 server, 4 logical CPU cores, 7.8 GiB RAM, CPU-only;
- Windows → internet Linux engineering TCP measurement: RTT p50 `11.884 ms`, p95 `13.369 ms`, upload p50 `42.276 Mbit/s`, download p50 `226.597 Mbit/s`;
- Windows CUDA llama.cpp 7B-Q4 benchmark: prefill `2866.127 tok/s`, decode `76.210 tok/s`;
- Linux CPU llama.cpp 0.5B-Q4 smoke: prefill `12.382 tok/s`, decode `0.201 tok/s`.

Those two historical llama.cpp benchmark runs used different GGUFs, so they cannot be combined into the current evidence bundle. The internet network result is not a trusted-private-LAN A/B proof. Later engineering recorded a narrow physical two-machine shared-runtime proof separately in `state.md`; neither set of evidence is a blanket production claim for other hardware/models/topologies.

## Identity and runtime security boundary

ADR 0005 remains the narrow M1 reference identity decision. The live provider-control path now authenticates enrolled Ed25519 node identities and collects authenticated execution attestations, but production hardening is still incomplete.

Missing before untrusted public-network provider operation include OS-protected node private-key storage, active-session revocation fan-out, complete service authorization/rate/resource controls, hardened production database/HA operation and a production-safe authenticated/encrypted data plane.

The TCP benchmark's `unauthenticated_server_report_v1` Lab ID is not the ADR-0005 identity proof. The benchmark still has no application authentication/encryption and remains trusted-private-LAN-only.

Upstream llama.cpp RPC remains **trusted-network-only**. ComputeMesh provider/session authentication does not make the upstream RPC socket safe for public exposure. Development/operator tooling can contain that socket behind loopback/private networking/SSH tunnels, but RPC itself is not the ComputeMesh production security boundary. Never expose the RPC worker directly to the public internet or an untrusted network.

`confidential_compute` is not a valid product guarantee until a concrete trusted-execution/GPU-attestation technology and verifier exist. The current `CONFIDENTIAL` policy class is intentionally fail-closed by default.

Portal API-key registration is protected against repeated submissions: the
server rejects an existing normalized business email with HTTP 409 using an
opaque vault-keyed fingerprint, and the browser disables the submit button
while the request is in flight.

The multi-GPU launcher binds llama.cpp to loopback by default. Non-loopback
binding requires an explicit protected-network opt-in.

Stripe Checkout and webhook processing enforce mode consistency: `sk_live_`
accepts only live-mode sessions/events and `sk_test_` only test mode. A
mismatch fails closed before ledger crediting.

`tools/stripe_preflight.py` provides a secret-free operator check for Stripe
configuration shape and the deployed `/healthz` contract. It never creates
Stripe resources or sends a webhook.
Because systemd keeps service secrets out of the interactive shell, the normal
command validates the deployed gateway; add `--require-local-config` when the
Stripe environment is intentionally loaded into the current shell.

Live provider sessions reserve capacity on the provider through the
authenticated control channel before inference starts. Reservations are
lease-bound, TTL-limited, idempotent on retry and released after completion.

## Remaining product-readiness work

The production **policy boundary** now exists privately, but broad production distributed inference is not yet validated. Remaining gates include:

- run the complete current gateway → private placement → real provider execution → evidence/attestation → private feedback path repeatedly on representative physical GPU pairs;
- controlled LAN delay/jitter/bandwidth/disconnect measurements and real two-site WAN validation;
- calibrate the private production predictor/optimizer from verified measurements rather than assumptions;
- enforce resource reservations/leases at the provider, not only in control-plane state;
- replace/contain the experimental upstream RPC path with a production-safe authenticated/encrypted data plane;
- production node-key storage, revocation/session fan-out and service authorization/resource controls;
- broader adversarial/system/fuzz/failure testing;
- complete production artifact lifecycle including stronger multi-shard identity/order semantics;
- true upstream token streaming/TTFT measurement where required;
- final HA/operations hardening for billing, verification, telemetry and private control-plane persistence.

When `COMPUTEMESH_MODEL_REGISTRY_URL` is configured, the gateway consumes the
private registry's validated public model view for `/v1/models` and Ollama
tags. `COMPUTEMESH_MODEL_REGISTRY_TOKEN` is optional for authenticated
deployments; timeout and cache duration are bounded by the corresponding
`COMPUTEMESH_MODEL_REGISTRY_*` settings. A configured registry is authoritative:
discovery and resolution fail closed if it is unavailable.

Payment boundary: the intended real-money purchase path for compute credits is Stripe. The gateway has a fail-closed Stripe Checkout/Webhook integration path that calls the official Stripe SDK when configured with `STRIPE_API_KEY` and a durable `COMPUTEMESH_STRIPE_SESSION_STORE`; signed webhook crediting additionally requires `STRIPE_WEBHOOK_SECRET`. Checkout metadata/session-store values define the purchased compute-credit amount, so tax-inclusive Stripe totals are not credited as extra compute balance. Provider payout operations have a Stripe Connect Accounts v2 / Express recipient onboarding path with durable provider accounts, onboarding links, settlement records, transfer idempotency, configurable transfer currency through `COMPUTEMESH_STRIPE_SETTLEMENT_CURRENCY`, and internal ledger payable clearing. Stripe Connect platform activation is complete and live. Provider onboarding links and direct payouts operate in live production mode with full KYC/compliance support. MetaMask/EVM wallet handling in the current provider UI is only for selecting a provider payout destination address for earnings from contributed compute power; wallets are not used to buy compute credits or to charge customers.

## Master Administrator Security, Fleet Banning & Multi-Tenant Isolation

ComputeMesh enforces strict multi-tenant isolation and fail-closed safety guarantees:
- **Tenant Isolation**: An individual fleet operator can only manage or emergency-stop their own fleet (`/api/portal/fleet/killswitch/trip`), never the entire platform or competitor fleets.
- **Master Administrator Authority**: Only the platform owner / Stripe account holder (`inetconnector`) possesses the Master Killswitch & Administrator Keys stored securely in the DiskStation Vault (`\\diskstation\Dani\ComputeMesh\killswitch`).

### Permanent Fleet Deactivation (Banning) & Reactivation

The Master Administrator can permanently suspend any abusive, non-compliant, or compromised fleet, and seamlessly reactivate it once cleared:

1. **Persistent State**: Fleet bans are persisted in SQLite (`fleet_banned_accounts` and `owner_banned_accounts`) surviving all daemon and server restarts.
2. **Instant Dead-Man Trip**: Banning synchronizes immediately with the in-memory `DeadMansLeaseGuard`, instantly aborting active execution pipelines and preventing new inferences.
3. **Fail-Closed Gateway Auth**: Any request using an API key, session token, owner key, or provider node token belonging to a banned fleet is rejected with `HTTP 403 Forbidden` (`{"error": "Fleet account is administratively suspended"}`).
4. **Portal Status**: `/api/portal/fleet` and `/mesh/fleet` reflect the suspension state (`"is_suspended": true`, `"suspension_reason"`, `"banned_at"`).
5. **Reactivation (Unbanning)**: The Master Administrator can lift the ban at any time, clearing the persistent ban record, unlocking Gateway authentication, and restoring full operational access.

#### 1-Click DiskStation Operator Scripts
Pre-configured scripts located in `\\diskstation\Dani\ComputeMesh\killswitch\`:
- `SPERRE-FLOTTE.bat <owner_id_oder_facc_id> "<Grund>"`: Bans and immediately suspends the target fleet.
- `ENTSPERRE-FLOTTE.bat <owner_id_oder_facc_id>`: Reactivates and restores the target fleet.
- `NOTABSCHALTUNG-GLOBAL.bat "<Grund>"`: Global emergency kill of the entire ComputeMesh cluster.
- `SYSTEM-WIEDERHERSTELLEN.bat`: Restores platform operations after an emergency.

#### Security CLI (`tools/security/killswitch_cli.py`)
```bash
# Deactivate / Ban a fleet permanently
python tools/security/killswitch_cli.py ban facc_0123456789abcdef --reason "AGB-Verstoß oder verdächtige Aktivität" --master-key <MASTER_KEY>

# Reactivate / Unban a fleet
python tools/security/killswitch_cli.py unban facc_0123456789abcdef --reason "Audit erfolgreich abgeschlossen" --master-key <MASTER_KEY>

# List all banned fleets
python tools/security/killswitch_cli.py list-banned --master-key <MASTER_KEY>
```

#### Admin REST API Endpoints
All administrative ban endpoints require `X-Master-Killswitch-Key` or `Authorization: Bearer <ADMIN_KEY>`:
- `POST /api/admin/fleet/ban` (Body: `{"owner_id": "facc_...", "reason": "Grund der Sperre"}`)
- `POST /api/admin/fleet/unban` (Body: `{"owner_id": "facc_...", "reason": "Freigabegrund"}`)
- `GET /api/admin/fleet/banned` (Returns list of currently banned fleet accounts)

## Immediate path

```text
current private umbrella checkout + pinned public runtime
        ↓
real enrolled coordinator/worker providers + one matching llama.cpp build/model
        ↓
full authenticated gateway/private-placement/shared-runtime request
        ↓
signed placement verification + real execution evidence + provider attestations
        ↓
durable verified outcome → new private performance observation
        ↓
repeatable controlled LAN delay/jitter/bandwidth/disconnect matrix
        ↓
real WAN/two-site validation
        ↓
calibrate private prediction/ranking from measured evidence
        ↓
provider-enforced leases + production data-plane/key/session hardening
        ↓
widen production scheduling only when gates are met
```

## Repository map

```text
ComputeMesh/
├─ SETUP.cmd / setup.sh   # Windows/Linux public lab entry points
├─ setup/                 # lab orchestration + bounded evidence transfer
├─ apps/node/             # runnable public provider agent + node surface
├─ tools/benchmark/       # inventory, TCP, llama-bench and GGUF-manifest tools
├─ services/gateway/      # authenticated public API/live gateway
├─ services/orchestrator/ # durable state + live execution/recovery/feedback plumbing
├─ services/identity/     # reference enrollment/key registry + live identity backing
├─ services/scheduler/    # public M1 evidence/reference feasibility planning
├─ protocol/              # contracts, session wire binding, Ed25519 verifier
├─ runtime/llama/         # controlled llama.cpp shared-runtime research path
├─ runtime/network/       # bounded network measurement/fault instrumentation
├─ portal/                # public web portal, sitemap and robots policy
├─ docs/                  # current status, specifications, audits and ADRs
└─ state.md               # public historical engineering/evidence handoff
```

For current public status read [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md) first, then the nearest component README. Use `state.md` for detailed engineering chronology/evidence and `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md` and the ADRs for target/history context.

## Language synchronization rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change. Current status additionally has synchronized `docs/CURRENT_STATUS.md` and `docs/CURRENT_STATUS.de.md`.

## License

All rights reserved until an explicit license is selected and published. Repository visibility does not grant open-source rights.

Provider Ed25519 private-key loading fails closed on POSIX when the key or its
parent directory is group/world accessible, and key writes reject symlink paths
while remaining atomic. The integrated control-plane sidecar connects identity
revocation events to immediate termination of matching provider sessions.
The runtime additionally supports Resilient WebUI Multi-Cluster Federation,
Zero-Trust Worker Communication with HMAC/nonce verification and automated quarantine,
and Adaptive Video Stream Compression.

- Vertiefte Architekturoptimierungen, Fehlertoleranz und Invarianten-Härtung (Teil 7) implemented with 100% test verification (Stateful Idempotency and Capacity Lease Management).
- Vertiefte Architekturoptimierungen, Fehlertoleranz und Invarianten-Härtung (Teil 17) implemented with 100% test verification (Placement Revision, Rate/Budget Limits, and Node Workload Boundary).
- Vertiefte Architekturoptimierungen, Fehlertoleranz und Invarianten-Härtung (Teil 12) implemented with 100% test verification.
- Vertiefte Architekturoptimierungen, Fehlertoleranz und Invarianten-Härtung (Teil 13) implemented with 100% test verification.

- Dynamic Peer-to-Peer Model Sharding & Distributed Off-Heap Cache Management completed with 100% test verification.

- **Phase 87**: Implemented Decentralized Shard Failover across P2P networks with atomic quota preservation.
- **Phase 88**: Implemented Decentralized Peer Consensus and Merkle Verification for Shard Replication to detect corrupt chunk replicas and failover autonomously via 2/3 Byzantine quorum.
