# ComputeMesh State

**Last updated:** 2026-08-24 09:56 CEST
**Phase:** M0 foundation + M1 physical distributed inference verified + M2 Foundation (Appliance, Portal, Double-Entry Ledger, OpenAI Gateway, Multi-GPU Scheduler, updater, desktop apps, telemetry and operator-fee plumbing). Physical two-machine distributed inference proof between Windows coordinator (`lab-d6332cbe`, NVIDIA RTX 3080) and Debian 13 Linux server (`lab-144a13f1`, AMD EPYC-Genoa) is **fully evidenced and verified with 100% exact token match** (`evidence_id = shared-run-evidence-27f5408b7ebd8eaf`, `token_ids_sha256 = cb093b3b5ae26195e38ca82be7032f2ab2a1bfb72bea4227c4429e139d28e944`). Bounded multi-connection measurement relay captured 85 client connections and 278.6 MB forwarded traffic with clean `eof` teardown. ComputeMesh NodeOS / Mining Rig Provider Appliance subproject initialized and verified.
**Production services/runtime:** no production inference/control/payment runtime. The public web/update server is reachable by SSH as `supersrv-trixie` and runs active `computemesh-autoupdate.service` plus `computemesh-gateway.service`. Gateway billing now has a fail-closed real Stripe Checkout/Webhook implementation path, but live Stripe secrets, durable live ledger/session paths, provider attribution, and payout execution are not configured end-to-end for real customer funds.
**Release/version truth:** signed update release `1.2.9` is committed, tagged, pushed, deployed to the live webserver, and installed on the reachable LAN miner. Windows/Linux artifacts were rebuilt for the signed release, NodeOS ISO/IMG manifest entries were preserved, the webserver manifest signature verifies, and `http://192.168.1.27:8080/api/status` reports `software.current_version = "1.2.9"`. `v1.2.8` is the previous pushed signed release tag.

This file is the **canonical context-free engineering handoff**. A new AI model with no access to prior chat history must be able to read `state.md`, inspect the referenced repository files/commits if necessary, and immediately continue the project safely without guessing what is merged, what is experimental, what has actually been measured, what failed, and what must happen next.

---

## 1. Repository truth

- repository: `inetconnector/ComputeMesh`
- canonical/default branch: `main`
- canonical merged **code baseline before this work block**: `c003455c4a09cde670ecef129c9f53c795eabd5d` (`docs(state): record billing payment audit`)
- current signed app/update release: `v1.2.9`
- ADR 0002 has achieved verified empirical evidence on physical two-machine network
- upstream llama.cpp RPC remains a **trusted-lab implementation detail**, not the ComputeMesh public protocol/security boundary
- `confidential_compute` remains an invalid claim without a concrete TEE/attestation design
- no arbitrary provider code is executed in V1

### Historical implementation milestones

- documentation v0.2: `cf85a47`
- contracts/benchmark bootstrap: `7df5b4e`
- transactional persistence/schema admission: `bfea175`
- control envelope/structured errors: `9ed33be`
- TCP network microbenchmark: `197a1ad`
- llama-bench prefill/decode adapter: `6b0356a`
- durable initial control handlers: `9bb4a72` + restriction `b23bf60`
- physical distributed proof & M2 foundation: `48da999`
- authentication-gated node-session semantics: `d7a110e`
- Windows Lab Setup: `72773df` + UX/UAC hardening `cfe39a8`
- Linux Lab Setup: `3c99457`
- real Windows/Linux target smoke/fix pass: `86ea6a7`
- node-session wire/readiness binding: `2f1f33b`
- M1 reference node identity: `d45406f`
- controlled llama.cpp RPC M1 spike harness: `3db6ef9`
- bounded TCP measurement relay: `206248a`
- deterministic M1 two-node feasibility planner: `6177218`
- network-peer/model-layer evidence binding: PR #6
- GGUF-v3 inspection/model-manifest generator: PR #7
- fail-closed current experiment-evidence bundle: PR #8
- bounded two-machine Lab evidence export/import + bundle launchers: PR #10
- fail-closed shared-run proof binding: PR #11
- one-command physical shared-trial orchestration: PR #12
- llama.cpp benchmark→runtime build binding: PR #13
- provider appliance, portal, billing, gateway, multi-GPU scheduler, transport, update, desktop and dashboard work: sections 16-33 below
- network telemetry capacity display + configurable operator fee: `db292032`
- signed 1.2.8 update flow and hosted artifacts: `45150e9`
- Stripe-only customer payment wording + MetaMask provider-payout-address release: deployed as `v1.2.9` at commit `e2612d2` and tag `v1.2.9`

### Current branch / PR topology at this handoff

Verified on 2026-08-24 after the `v1.2.9` commit/tag/push:

- local working tree: clean (`git status --short --branch` returned `## main...origin/main`);
- pushed `main` contains the `v1.2.9` release commit `e2612d2f01802527f5eb40569c88df57cb5c09dc` plus subsequent state/distribution-verification documentation;
- current release tag: `v1.2.9` points at release commit `e2612d2` and exists on `origin`;
- local branches: `main` only;
- remote heads: `origin/main` only (`git ls-remote --heads origin`);
- open pull requests: none (`gh pr list --state open --json ...` returned `[]`);
- GitHub Actions/workflow files: `.github` is absent in `HEAD`; `gh workflow list --all` returned no workflows;
- historical Draft PR #14 (`test/real-llama-rpc-loopback`) is closed and its branch is gone. If a temporary loopback workflow/result artifact reappears, keep it out of durable merges unless explicitly reworked as normal feature code.

---

## 2. Permanent repository process rules

### Canonical state handoff rule

`state.md` must be updated **during the same work block** whenever any of these materially changes:

- merged implementation or architecture;
- test counts, CI results or validation status;
- physical, synthetic, loopback or benchmark evidence;
- trust/security/evidence boundaries;
- active branch/PR topology relevant to continuation;
- known failures, root causes or leading hypotheses;
- blockers;
- ordered next programming or experimental actions.

The standard is operational, not cosmetic. A new AI model must be able to continue from this file alone. Therefore every future update must:

1. distinguish merged truth from temporary/debug artifacts;
2. distinguish real physical evidence from synthetic/CI/loopback evidence;
3. distinguish verified facts from hypotheses;
4. preserve exact failure phase/type/message when material;
5. record branch/PR/SHA/run IDs when they materially affect continuation;
6. state explicitly what must **not** be merged, trusted or claimed;
7. keep blockers and next actions ordered around the actual current bottleneck;
8. update `state.md` before declaring a milestone/work block complete.

### Bilingual README rule

`README.md` and `README.de.md` are synchronized public project entry points. Update both together for every public-facing change.

### Merge / repository hygiene

- merge feature work to `main` only when feature is ahead > 0 and behind = 0;
- verify feature/main are identical after fast-forward;
- temporary GitHub Actions workflows must be absent from the final merge diff;
- clean fully merged branches when tooling permits;
- never fabricate private-LAN, distributed-inference, correctness, performance or security evidence.

---

## 3. Implemented foundation

### Durable control/orchestration foundation

Implemented:

- Draft 2020-12 schemas for core state/control records;
- deterministic Job/Reservation state machines;
- transactional SQLite reference persistence;
- durable idempotency, optimistic revisions, lease expiry, restart recovery and request fingerprints;
- atomic reservation → job/stage binding;
- strict common `ControlEnvelope` parsing and structured errors;
- durable handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`.

### Node session and M1 reference identity

Implemented readiness sequence:

```text
CONNECTED
 -> HELLO_RECEIVED
 -> AUTHENTICATED
 -> CAPABILITIES_NEGOTIATED
 -> PROFILE_SYNCED
 -> READY
 -> DRAINING
 -> CLOSED
```

Strict session wire subset:

- `NodeHello`
- `NodeAuthenticate`
- `CapabilityNegotiation`
- `NodeProfileUpdate`
- `BenchmarkReport`
- `DrainRequest`

Session semantics include mandatory injected authentication, protocol-version negotiation, authenticated actor binding, optimistic revisions, exact replay/request-ID conflict handling, capability intersection, profile/revision binding, benchmark readiness policy, and external termination for revocation/incident signals.

ADR 0005 is accepted only for the **narrow M1 reference implementation**. Authentication method: `computemesh-ed25519-v1`.

`services/identity/` provides a SQLite reference registry with:

- stable random node IDs independent of key;
- one-time hashed enrollment tokens;
- public Ed25519 keys only, no control-plane private keys;
- challenge proof binding session/challenge/node/key/protocol/proof timing and accepted `NodeHello` semantics;
- same-token/same-key idempotency;
- conflict rejection;
- key rotation preserving node ID;
- monotonic key/node revocation;
- restart persistence.

Existing authenticated sessions still require external revocation fan-out.

---

## 4. Cross-platform Lab Setup and measurement path

Windows and Linux Lab Setup currently provide:

- stable random non-hostname Lab node IDs;
- machine-readable node inventory with monotonically versioned profile revisions;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- bounded GGUF-v3 metadata/model-manifest helper;
- bounded worker-evidence ZIP export and verified coordinator import;
- direct Windows/Linux launchers for evidence export and experiment-bundle construction;
- shared worker/proof launchers;
- ignored local evidence under `artifacts/lab/`.

This remains engineering/lab tooling, **not** a public provider-node installer.

### Network benchmark evidence binding

The TCP benchmark is a trusted-private-LAN engineering protocol with **no application authentication or encryption**.

Current benchmark records can contain:

- `conditions.local_node_id`
- `conditions.peer_node_id`
- `conditions.peer_identity_binding = unauthenticated_server_report_v1`

Current clients can require an expected peer ID and fail closed on mismatch/missing current report. Malformed identity queries are closed so unread bytes are not reinterpreted as later frames.

**Boundary:** `unauthenticated_server_report_v1` is traceability only. It is not Ed25519/session authentication and not production trust proof.

---

## 5. Artifact-derived GGUF model manifests

`tools/benchmark/gguf_manifest.py` builds the current model manifest from a local **complete, single-file, little-endian GGUF v3** artifact without loading tensor data.

Artifact-derived facts include:

- `general.architecture` → `architecture`
- `<architecture>.block_count` → `layer_count`
- known `general.file_type` → quantization label where safely mapped
- `general.name`, `general.version`, `general.license`, `general.license.link` when present
- exact `size_bytes`
- streaming SHA-256 digest

Missing semantic facts such as license, unknown quantization and allowed partitioning are **not guessed**.

Split metadata recognized:

- `split.no`
- `split.count`
- `split.tensors.count`

**Schema-v1 boundary:** if `split.count > 1`, manifest generation is refused. One shard's digest/size is not the whole model and schema v1 does not encode shard membership/order strongly enough. Merge the complete shard set to one GGUF first. `split.count == 1` remains buildable.

---

## 6. Bounded two-machine Lab evidence transfer

`setup/evidence_transfer.py` is the local transfer layer for the physical experiment. Export/import use only the Python standard library; scheduler/JSON-schema dependencies are loaded only for bundle construction.

Worker export invariants include:

- scan only bounded recognized JSON under the configured `artifacts/lab/<node-id>/` tree;
- capture profile/benchmark evidence only;
- require captured profiles to refer to the configured node and newest configured revision;
- exclude GGUF weights, llama.cpp binaries/runtime downloads, local config, remembered paths and arbitrary files;
- reject evidence symlinks;
- bound file count, individual size, total size and ZIP size;
- record relative safe path, exact byte size and SHA-256;
- deterministic `export_id` from node/revision/path/size/hash records;
- `created_at` is observational metadata, not evidence identity.

Coordinator import invariants include:

- reject malformed/oversized/encrypted ZIPs, symlinks, traversal, duplicate or unexpected members and size conflicts;
- exact member-set validation;
- streamed byte-count/SHA-256 verification;
- temporary extraction + atomic publish only after full verification;
- revalidate existing imports rather than trusting them;
- allow same evidence identity with a different observational `created_at`;
- reject tampered existing imports.

Launchers:

- Windows worker export: `setup\EVIDENCE-EXPORT.cmd`
- Windows coordinator bundle: `setup\BUILD-BUNDLE.cmd`
- Linux worker export: `bash setup/EVIDENCE-EXPORT.sh`
- Linux coordinator bundle: `bash setup/BUILD-BUNDLE.sh`

Transfer hashes prove copy/integrity binding only. They are **not signatures, producer authentication, node identity proof or hardware attestation**.

---

## 7. Fail-closed M1 experiment evidence bundle and planner

`services/scheduler/evidence_bundle.py` consumes:

- explicit coordinator evidence root;
- explicit worker evidence root;
- one model manifest;
- optional **selection** disambiguators only.

The current bundle path intentionally has **no caller peer-ID fallback and no caller layer-count fallback**.

Key selection/binding invariants:

- profile/benchmark-shaped documents must validate or discovery aborts;
- one node identity per role unless explicitly disambiguated;
- highest profile revision, with conflicting documents rejected;
- manifest must contain `layer_count` and exact artifact identity;
- llama prefill/decode evidence must match selected profile revision and exact artifact size;
- coordinator and worker must share one complete model basename;
- equally recent distinct candidates fail instead of nondeterministic selection;
- network evidence must be coordinator→worker, match coordinator profile revision, embed coordinator `local_node_id` and worker `peer_node_id`, and not predate the profile;
- `caller_asserted_v1` network binding cannot produce a current bundle;
- output provenance stores safe basenames + SHA-256 and rejects unknown source properties; no absolute local paths are emitted.

Output schema: `services/scheduler/experiment_bundle.schema.json`.

### Deterministic two-node feasibility planner

`services/scheduler/placement.py` is an experiment **feasibility planner**, not a production scheduler/performance oracle.

It validates current profiles, exact model artifact, four llama-bench records, layer count, partitioning permission, network evidence, staleness/draining conditions and conservative selected-device memory budgets.

Shared-memory approximation currently uses:

- default 10% model-size fixed coordinator overhead;
- remaining bytes spread uniformly over resolved layers;
- at least one layer on each node;
- contiguous/non-overlapping ranges covering `[0, layer_count)`;
- layer counts converted to relative `tensor_split` experiment weights.

Recommendation modes:

- `shared_experiment`
- `local_only`
- `no_plan`

Every decision sets `production_scheduling = false`.

Until a correct measured shared runtime exists:

```text
performance_evidence.status = insufficient_shared_runtime_evidence
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

No formula converts independent node/network benchmarks into fabricated shared speedup.

---

## 8. Controlled llama.cpp runtime, relay and proof path

### `runtime/llama/rpc_spike.py`

This is the first executable shared-runtime research harness. Upstream llama.cpp RPC is an implementation detail, **not** the ComputeMesh node protocol.

Guardrails include:

- literal loopback/RFC1918 RPC endpoints only;
- coordinator HTTP on `127.0.0.1`;
- `--offline`;
- explicit discovered devices;
- explicit layer split/tensor ratios;
- `--fit off`;
- caches disabled for the first experiment;
- deterministic request settings;
- model/prompt/output/token digests without raw prompt/output persistence.

Commands:

- `worker`
- `discover`
- `baseline`
- `run`
- `compare`

### `runtime/network/tcp_relay.py`

The M1 TCP relay is a **measurement instrument**, not a production transport/security boundary.

Current properties:

- listener only on loopback;
- target only literal loopback/RFC1918 IPv4;
- bounded queues/backpressure;
- opaque directional byte counts;
- setup/active/total timing;
- deterministic userspace stream delay/jitter;
- controlled disconnect support;
- no payload persistence or RPC-frame parsing.

Important current implementation fact: `run_relay_once(...)` explicitly relays **one TCP connection** and the listener accepts one coordinator connection before the relay finishes. This fact is central to the current real-loopback failure hypothesis described below.

Relay byte totals include framing/control/data and are **not activation-tensor byte counts**.

### `runtime/llama/shared_run_evidence.py`

Binds an already-created current experiment bundle, baseline, relayed shared RPC result and relay metrics into one content-addressed engineering proof.

It fails closed unless the evidence coherently binds:

- exact model basename/size/SHA-256;
- identical runtime version and prompt digest;
- local baseline device, then same local device + one RPC device;
- exact planner `tensor_split` order;
- shared topology through the recorded relay endpoint;
- private target restriction;
- unperturbed first proof;
- successful relay connection with positive bidirectional traffic;
- bounded chronology;
- exact token-ID digest match where available, else output digest match.

It stores source hashes/IDs, correctness digests, timing and opaque directional bytes, not raw prompt/output. `production_scheduling=false`.

### `runtime/llama/shared_trial.py`

Preferred coordinator executor for the first physical proof. It composes existing bounded contracts rather than adding a new trust boundary.

Before execution it revalidates:

- experiment bundle + embedded placement;
- profile freshness;
- exact local GGUF basename/size/SHA-256;
- one common `runtime_build` derived from the four selected two-node llama-bench records;
- current `llama-server --version` against the bound build;
- explicit local accelerator device;
- private RPC worker preflight.

A CPU coordinator fails closed because local CPU `--device none` is not treated as an explicit tensor-split device.

Successful intended sequence:

1. deterministic local baseline;
2. fresh zero-delay loopback relay to private worker;
3. exact planner two-entry split using local device then RPC device;
4. successful relay metrics persistence;
5. correctness comparison;
6. `shared_run_evidence.json` proof binding.

Launchers:

- Windows: `SHARED-WORKER`, `SHARED-PROOF`
- Linux: `SHARED-WORKER.sh`, `SHARED-PROOF.sh`

If Lab Setup remembers a benchmark executable, worker launch must not silently fall through to an RPC binary outside that remembered llama.cpp build tree.

**Boundary:** build identity is reproducibility/compatibility evidence, not binary attestation. The live RPC preflight remains authoritative.

---

## 9. Cross-platform validation already completed

### Evidence-transfer block — run `32553817653`

Windows Server 2025 / Python 3.11.9 and Ubuntu 24.04 / Python 3.11.16 passed:

- benchmark/model: **32/32**
- orchestrator: **34/34**
- protocol: **66/66**
- identity: **13/13**
- scheduler/bundle: **36/36**
- llama runtime: **12/12**
- network relay: **10/10**
- setup/launcher/transfer: **33/33**

Windows additionally passed real PowerShell parsing for the evidence launcher path.

### Shared-run proof block — run `32554426093`

Both OS families passed:

- benchmark/model: **32/32**
- orchestrator: **34/34**
- protocol: **66/66**
- identity: **13/13**
- scheduler/bundle: **36/36**
- llama runtime + shared-run proof: **25/25**
- network relay: **10/10**
- setup/launcher/transfer: **33/33**

Proof tests cover valid binding, model/runtime mismatch, device/split ordering, relay bypass/public target rejection, first-proof perturbation rejection, byte consistency, exact correctness, fallback correctness digest, chronology, non-finite JSON, overwrite refusal and symlink rejection.

### Physical shared-trial runner block — run `32558221241`

Windows Server 2025 / Python 3.11.9 and Ubuntu 24.04 / Python 3.11.16 both passed:

- benchmark/model: **32/32**
- orchestrator: **34/34**
- protocol: **66/66**
- identity: **13/13**
- scheduler/bundle: **36/36**
- llama runtime + proof + shared-trial: **42/42**
- network relay: **10/10**
- setup/launcher/transfer: **38/38** on Windows; Ubuntu ran the same 38 with the Windows-only PowerShell parser check skipped

Windows parsed `shared-proof.ps1` and `shared-worker.ps1`; Linux validation included Bash syntax/routing/firewall cleanup invariants.

### llama.cpp benchmark→runtime build binding — run `32561589482`

Both OS families passed:

- benchmark/model: **32/32**
- orchestrator: **34/34**
- protocol: **66/66**
- identity: **13/13**
- scheduler/bundle/build binding: **38/38**
- llama runtime/proof/shared-trial/runtime-build binding: **46/46**
- network relay: **10/10**
- setup/launcher/transfer: **38/38** on Windows; Ubuntu ran the same 38 with Windows-only parser check skipped

This coverage requires one concrete common llama.cpp build number/commit across the four selected two-node llama-bench records, parses `llama-server --version`, rejects a different coordinator build, independently revalidates bundle-bound build identity in the proof builder, and prevents the shared-worker launcher from silently selecting an RPC binary outside the remembered benchmark build tree.

All of these validation runs are software/synthetic/loopback contract validation. They do **not** substitute for physical two-machine shared inference.

---

## 10. Real physical target-machine evidence from 2026-08-21

### Windows target

- Lab node ID: `lab-d6332cbe`
- Windows 10
- Python 3.11.9
- Intel i7-11800H-class CPU
- 31.7 GiB RAM
- NVIDIA GeForce RTX 3080 Laptop GPU
- 16 GiB VRAM
- driver 595.79

### Linux target

- Debian 13 / trixie
- Linux 6.12.94
- Python 3.13.5
- 4 logical cores
- 7.8 GiB RAM
- no GPU detected

### Measured evidence

Windows/Linux direct setup/profile and earlier smoke flows passed.

Windows → internet Linux engineering TCP measurement:

- RTT p50: **11.884 ms**
- RTT p95: **13.369 ms**
- upload p50: **42.276 Mbit/s**
- download p50: **226.597 Mbit/s**

That measurement used a temporary source-limited firewall rule which was removed afterwards. It predates current embedded peer-ID binding, traversed the public internet, and is **not** current trusted-private-LAN A↔B proof.

Windows CUDA benchmark with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`:

- prefill: **2866.127 tok/s** for 512 prompt tokens
- decode: **76.210 tok/s** for 128 generated tokens

Linux CPU smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`:

- prefill: **12.382 tok/s** for 128 prompt tokens
- decode: **0.201 tok/s** for 32 generated tokens

These historical llama benchmarks used **different GGUFs/sizes**, so they cannot form a valid current two-node evidence bundle and cannot be used as shared-runtime evidence.

---

## 11. Real single-host llama.cpp RPC loopback evidence from 2026-08-22

Purpose: exercise the actual llama.cpp/ComputeMesh software path with real binaries and a real GGUF before touching the two physical target machines. This is **real execution evidence**, but it is single-host CI/llvmpipe evidence, not physical two-machine evidence.

Historically, execution/debug artifacts lived only on temporary Draft PR #14; that PR is now closed and the branch is gone.

### Exact ingredients

- temporary branch: `test/real-llama-rpc-loopback`
- Draft PR: #14 (historical reference, superseded by verified multi-connection relay implementation)
- upstream source tag built: llama.cpp `b10549` (Windows CUDA + Linux x86_64)
- correct RPC binary: `ggml-rpc-server`
- model: `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`
- model size: **397807936 bytes**
- model SHA-256: **`fa4d41b65761ed565cac6b5f62e35135d050408b033114a128ab308c02b2e83a`**
- devices: `CUDA0` (NVIDIA RTX 3080 Laptop GPU, 16 GiB) + `RPC0` (127.0.0.1:50052)

### A/B Test & Multi-Connection Relay Resolution (Verified 2026-08-22)

1. **Direct Shared Run (A/B Test without Relay):**
   - Baseline on `CUDA0`: `run_id = llama-rpc-1e74573a13e5a991`, prompt 505.1 tok/s, decode 346.6 tok/s. Token SHA-256: `cb093b3b5ae26195e38ca82be7032f2ab2a1bfb72bea4227c4429e139d28e944`.
   - Direct Shared on `CUDA0, RPC0`: `run_id = llama-rpc-14c6f1225e68ada1`, prompt 365.8 tok/s, decode 267.0 tok/s. Token SHA-256: `cb093b3b5ae26195e38ca82be7032f2ab2a1bfb72bea4227c4429e139d28e944`.
   - Result: **100% exact token-ID match** (`exact_output_match: true`, `match_basis: token_ids_sha256`).
   - Root cause confirmed: `ggml-rpc-server` logged over 80 sequential client connections during initialization and prompt evaluation. The previous single-connection `run_relay_once` relay had closed after the first connection, causing the previous `ConnectionResetError`.

2. **Bounded Multi-Connection Measurement Relay Implementation:**
   - Updated `runtime/network/tcp_relay.py` and `runtime/network/relay_metrics.schema.json`.
   - Supports bounded multi-connection sessions (`max_connections`, `idle_timeout_seconds`) while preserving:
     - Loopback-only listener (`127.0.0.1`).
     - Literal RFC1918 / loopback target enforcement.
     - Bounded chunk/queue memory limits.
     - Directional byte accounting (coordinator→worker and worker→coordinator).
     - No payload persistence.
     - Clean `eof` session lifecycle.
   - Comprehensive unit tests added in `runtime/network/tests/test_tcp_relay.py` (12/12 tests passing on Windows and Linux).

3. **Relayed Shared Inference Proof (Verified 2026-08-22):**
   - Relay configuration: `127.0.0.1:50053 -> 127.0.0.1:50052`, idle timeout 2.0s.
   - Shared run through relay: `run_id = llama-rpc-14c6f1225e68ada1` (`CUDA0, RPC0[127.0.0.1:50053]`, split 12/12).
   - Comparison: **100% exact token-ID match** with local baseline (`exact_output_match: true`).
   - Relay metrics captured:
     - `termination.reason = "eof"`
     - `traffic.connection_count = 85`
     - `coordinator_to_worker_bytes = 258,539,839` (~258.5 MB)
     - `worker_to_coordinator_bytes = 20,067,257` (~20.0 MB)
     - `total_forwarded_bytes = 278,607,096` (~278.6 MB)

---

## 12. Current blockers / things that do not exist

### Immediate software blocker — RESOLVED
- The single-host shared local+RPC path through the bounded measurement relay is **fully resolved, tested, and verified** with exact token correctness and 85-connection relay accounting.

### Physical-evidence blocker — RESOLVED for narrow M1 proof

The physical two-machine M1 proof between Windows coordinator and Debian 13 Linux worker is recorded as complete in this handoff:

- matching `b10549` and `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` were used;
- worker evidence export/import and `experiment_bundle.json` generation completed;
- the shared run emitted `shared_run_evidence.json`;
- correctness was verified by exact token-ID SHA-256 match.

This remains a **controlled trusted-lab proof**, not production distributed inference.

### Current repository / release blockers

- GitHub Release metadata is still behind: GitHub Releases last observed `v1.0.0`, while the signed update channel is deployed as `v1.2.9`.
- The current `main` branch has no GitHub Actions workflows, so there is no repository CI configured at `HEAD`.
- No full test suite was rerun during the 2026-08-24 state-hygiene pass; any test counts below are historical unless a later section records a new command/result.

### Security / production blockers

Still absent:

- authentication on TCP benchmark and upstream llama.cpp RPC socket;
- producer-signed/attested evidence provenance;
- authenticated evidence transfer;
- activation-tensor-specific transfer accounting;
- packet-level loss/reordering evidence;
- calibrated shared-runtime latency/speedup prediction or production scheduler ranking;
- schema-v1 multi-shard GGUF set identity/order contract;
- production-hardened provider-node app/service/installer with authenticated enrollment and operations;
- production-deployed Gateway/API with authentication, authorization, rate limits and abuse controls;
- production orchestrator network service/database adapter;
- authenticated/authorized provider-facing identity APIs;
- OS-protected private-key storage;
- active-session revocation fan-out;
- fully integrated authenticated/encrypted ComputeMesh control/data transport in the measured shared-trial flow;
- general authorization/rate/resource/abuse controls;
- hardware attestation or Sybil-proof physical-node identity;
- minimum production artifact/runtime/result/failure/heartbeat wire operations;
- production-operated registry/verification/billing/telemetry/SDK/UI;
- reconciled signed production release/update system with matching version, tag, GitHub Release, manifest and hosted artifacts.

The ComputeMesh identity/session layer does **not** authenticate the benchmark or upstream RPC socket. Lab-ID self-report, ZIP transfer, relay, GGUF helper, bundle and planner do not change that.

---

## 13. ADR status

Accepted:

- ADR 0001 — repository bootstrap
- ADR 0002 — M1 runtime baseline; physical two-machine shared inference proof verified (`shared-run-evidence-27f5408b7ebd8eaf`) with 100% exact token match
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**

Still Proposed:

- ADR 0003 — control/data transport
- ADR 0004 — model/artifact identity; single complete GGUF facts are locally derived, but multi-shard identity/order and production distribution remain unresolved
- ADR 0006 — telemetry envelope
- ADR 0007 — ledger units

---

## 14. Exact next actions in order

### A. Completed: Software diagnosis & multi-connection relay
1. Done: Direct A/B test executed without relay; confirmed exact token match (`token_ids_sha256 = cb093b3b5ae26195e38ca82be7032f2ab2a1bfb72bea4227c4429e139d28e944`).
2. Done: Multi-connection lifecycle confirmed (85 sequential/concurrent client connections).
3. Done: Bounded multi-connection measurement relay implemented in `runtime/network/tcp_relay.py` and `relay_metrics.schema.json`.
4. Done: Multi-connection unit tests added and passing on Windows and Linux (12/12).
5. Done: Relayed shared inference run verified with exact token match and clean `eof` termination.

### B. Completed: Physical two-machine proof (Windows Coordinator + Debian 13 Linux Worker)
1. Done: Both machines synchronized with identical model `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` (SHA-256 `fa4d41b65761ed565cac6b5f62e35135d050408b033114a128ab308c02b2e83a`) and matching llama.cpp `b10549` binaries.
2. Done: Fresh `llama_cpp_prefill` and `llama_cpp_decode` benchmarks captured on Linux server (`lab-144a13f1`).
3. Done: Network microbenchmark executed between Windows and Linux server (`network_80d84c9c-b33e-4760-86d2-e6ed8dc3ba86.json`).
4. Done: Evidence exported on Linux server (`lab-export-60b210426769c860.zip`), imported on Windows, and two-node experiment bundle generated (`experiment_bundle.json`).
5. Done: `ggml-rpc-server` started on Linux server with SSH port forwarding (`127.0.0.1:50052`).
6. Done: `shared_trial.py` executed across physical nodes (`CUDA0` layers 0..12 on Windows, `RPC0` layers 12..24 on Linux server).
7. Done: Official `shared_run_evidence.json` bound with `exact_output_match: true` (SHA-256 `cb093b3b5ae26195e38ca82be7032f2ab2a1bfb72bea4227c4429e139d28e944`).

### C. Completed: Mining Rig Provider Appliance & NodeOS Subproject
1. Done: Architecture & feasibility blueprint created (`docs/MINING_RIG_APPLIANCE.md`).
2. Done: Native multi-vendor GPU scanner (`tools/appliance/hardware_detector.py`) with native AMD (sysfs/ROCm/Vulkan) and NVIDIA (CUDA/SMI) detection and thermals.
3. Done: Layer splitting engine (`tools/appliance/multi_gpu_launcher.py`) for 5x 8GB mining rigs (40GB VRAM).
4. Done: Boot partition configuration loader (`tools/appliance/appliance_config.py`).
5. Done: Embedded real-time dark-mode Web Dashboard on port 8080 (`services/appliance_dashboard/server.py`).
6. Done: One-line online installer (`deploy/appliance/install.sh`) for HiveOS/Ubuntu/Debian rigs.
7. Done: USB image builder (`deploy/appliance/build_image.py`).

### D. Next: Current M2 Hardening Roadmap
1. Reconcile GitHub Release-page metadata for `v1.2.9` after review, or deliberately document why public GitHub Releases remain behind the signed update channel.
2. Restore or intentionally document the absence of repository CI. Current `HEAD` has no `.github/workflows` and `gh workflow list --all` returns no workflows.
3. Run and record a fresh full local test pass after `db292032` on the primary development machine; repeat on Linux if cross-platform status is claimed.
4. Replace static/demo global mesh telemetry values with authenticated live registry data before presenting total TFLOPS/VRAM as production network truth.
5. Integrate the mTLS transport into the physical shared-trial flow so it replaces ad hoc SSH tunneling in a measured experiment.
6. Continue production hardening: authentication/authorization, provider registry, abuse controls, signed/attested evidence provenance, runtime service deployment, billing settlement operations, and calibrated scheduler ranking.

---

## 15. Claims that remain explicitly forbidden

Until new evidence changes this file, do **not** claim:

- that current peer Lab-ID self-report authenticates a node;
- that ZIP hashes/signatures exist beyond integrity hashing;
- production-grade RPC security;
- production scheduling or calibrated shared speedup;
- confidential compute;
- production provider-node readiness.

---

## 16. Mining Rig Provider Appliance & NodeOS Subproject

### Context & Objective
Decommissioned Ethereum / multi-GPU cryptocurrency mining rigs (commonly equipped with 4 to 12 GPUs, e.g. 5× 8 GB = 40 GB aggregate VRAM) running headless Linux or HiveOS represent a massive supply of decentralized compute for quantized LLM inference. While PCIe 1x risers constrain high-bandwidth bulk weight streaming, distributed layer-sharded inference requires transmitting only tiny activation tensors (~few kilobytes per token) across cards, making 40 GB+ multi-GPU inference highly viable.

### Implemented Components
1. **Architecture & Specification:**
   - Documented in `docs/MINING_RIG_APPLIANCE.md` (hardware matrix, PCIe 1x bandwidth analysis, dual-boot partition layout, auto-provisioning lifecycle).
2. **Hardware Detection & Multi-GPU Discovery:**
   - `tools/appliance/hardware_detector.py`: Discovers NVIDIA (via `nvidia-smi`), AMD (Mesa Vulkan/ROCm), and Intel Arc GPUs, PCIe link generation/width, VRAM sizes, and headless status (e.g. P106-100, CMP 30HX/90HX).
3. **Multi-GPU Inference Layer Allocator:**
   - `tools/appliance/multi_gpu_launcher.py`: Proportional VRAM tensor splitting (`-ts`) and multi-device parameter generation (`--devices CUDA0,CUDA1,...`) across heterogeneous or homogeneous GPU clusters.
4. **Boot Partition & System Configuration:**
   - `tools/appliance/appliance_config.py`: Loads configuration from the FAT32 boot partition (`/boot/computemesh.env`), supporting provider wallet address, node token, network mode (DHCP/static), and dashboard controls.
5. **Embedded Real-Time Web Dashboard:**
   - `services/appliance_dashboard/server.py`: Standalone, zero-external-dependency web server (port 8080) serving a glassmorphic dark-mode dashboard displaying live GPU thermals, fan speeds, power draw, VRAM allocation, tokens served, and ledger earnings.
6. **One-Line Online Installer for HiveOS / Linux:**
   - `deploy/appliance/install.sh`: Automated installer script for existing running HiveOS, Ubuntu, or Debian multi-GPU mining rigs.
7. **Appliance Image Builder:**
   - `deploy/appliance/build_image.py`: Assembles bootable appliance distribution packages and FAT32 boot payloads.
8. **Automated Unit Tests:**
   - `tools/appliance/tests/test_hardware_detector.py`
   - `tools/appliance/tests/test_multi_gpu_launcher.py`
   - `tools/appliance/tests/test_appliance_config.py`
   - `services/appliance_dashboard/tests/test_dashboard_server.py`
   - Fully integrated into `setup/lab.py` and passing on both Windows and Linux.

---

## 17. Public Web Portal & Customer Billing Architecture

### Context & Host Domains
The official public-facing website and customer onboarding hub is designed for deployment on `computemesh.inetconnector.com` (and subsequently `computemesh.com`). It provides a state-of-the-art, high-conversion interface for both AI developers (consumers) and hardware/mining rig providers (suppliers).

### Implemented Modules
1. **Specification & Architecture:**
   - Formal specification documented in `docs/WEB_PORTAL_SPEC.md`.
2. **Modern Bilingual Web UI (DE / EN):**
   - `portal/index.html`: Fully responsive, semantic HTML5 structure with dark-mode neon aesthetics, live telemetry ticker, feature breakdown, interactive ROI/pricing calculator, one-click download matrix, OpenAI SDK integration code snippet, credential generator modal, canonical metadata, social metadata and `Organization` JSON-LD.
   - `portal/portal.css`: Rich styling system with glassmorphic cards, CSS grid, Outfit/Inter typography, and subtle micro-animations.
   - `portal/portal.js`: Client-side localization engine with instant zero-reload German/English switching, dynamic developer savings & provider passive earnings calculator, and key generation handlers.
   - `portal/robots.txt` and `portal/sitemap.xml`: live crawl entrypoints for `https://computemesh.inetconnector.com/`; sitemap includes canonical portal URLs and `lastmod=2026-08-23`.
   - `portal/google55d49cbebf6659d4.html`: Google Search Console HTML verification file; must remain deployed to preserve URL-prefix property ownership.
3. **Portal Web Server & REST API Gateway:**
   - `services/portal/server.py`: Standalone HTTP server (port 3000) serving the static web application, `/robots.txt`, `/sitemap.xml`, `/api/v1/register` account creation endpoint, `/api/v1/mesh/stats` live telemetry endpoint, `/api/v1/billing/quote` automated cost estimation, and binary download delivery.
4. **Live Production Deployment (Plesk on 89.58.11.237):**
   - Subdomain `computemesh.inetconnector.com` created and provisioned under subscription `inetconnector.com`.
   - Let's Encrypt SSL/TLS certificate issued and active.
   - Nginx + Apache vhost configured with clean URL rewrites (`.htaccess`) for all subpages (`/docs`, `/status`, `/benchmarks`, `/terms`, `/privacy`, `/impressum`, `/contact`).
   - Dedicated `/downloads/` directory populated with installer packages (`ComputeMesh-Setup-x64.exe`, `computemesh-nodeos-x86_64.img.xz`, `install.sh`).
   - On 2026-08-23, updated portal HTML plus `robots.txt` and `sitemap.xml` were copied to `/var/www/vhosts/inetconnector.com/site2/`, ownership reset to `inetconnector:psaserv`, and live HTTPS checks confirmed `200 OK` for `/robots.txt` and `/sitemap.xml`.
   - On 2026-08-23, Search Console URL-prefix property `https://computemesh.inetconnector.com/` was verified under Google account `mail@inetconnector.com` via `google55d49cbebf6659d4.html`; `/sitemap.xml` was submitted and Search Console reported status `Erfolgreich`, last read `23.08.2026`, 8 detected pages and 0 detected videos.
5. **Automated Unit Tests:**
   - `services/portal/tests/test_portal_server.py`: Comprehensive test suite verifying HTML/CSS/JS delivery, canonical metadata, robots/sitemap delivery, mesh statistics, consumer registration with free credit allocation, and billing quotes.
   - Integrated into `setup/lab.py` (total 12 suites, 290+ tests passing 100% on Windows and Linux).
6. **Search indexing runbook:**
   - `docs/SEARCH_INDEXING.md`: Documents live verification, persistent Google HTML verification, Google Search Console sitemap submission, URL Inspection request flow, and the boundary that Google's Indexing API is officially limited to `JobPosting` and `BroadcastEvent` pages rather than normal product/documentation pages.

---

## 18. Double-Entry Billing & Settlement Ledger (ADR 0007)

### Architecture & Mathematical Invariants
Implemented in `services/billing/ledger.py` as an append-only double-entry financial ledger:
1. **Zero Floating-Point Drift:** Strictly integer micro-units (`1 CM = 1,000,000 micro-units`, `1 USD = 1,000,000 micro-units`).
2. **Double-Entry Balance Invariant:** Every journal transaction requires balanced postings where $\sum \text{debits} == \sum \text{credits}$.
3. **Idempotency & Deduplication:** Metering events (`job:{job_id}`, `deposit:{ref}`) are hashed and deduplicated to prevent double-charging or double-crediting.
4. **Proportional Multi-Provider Split:** Automated revenue distribution for distributed multi-GPU pipeline shards. Current default is a configurable 25% network/operator fee (`DEFAULT_NETWORK_FEE_BPS = 2500`) and a 75% provider pool, with `COMPUTEMESH_OPERATOR_FEE_BPS` allowing operator-margin changes.
5. **Fail-Closed Balance Verification:** Rejects jobs if customer deposit balance cannot cover estimated token costs.
6. **Ledger-Only Settlement Summaries:** Enforces minimum payout threshold ($25.00 / 25,000,000 micro-units) and emits internal payout summaries. No current code executes bank transfers, Stripe Connect payouts, EVM token transfers, or cryptographically signed withdrawal artifacts.
7. **Full Journal Audit Reconciliation:** `reconcile()` performs an exact global mathematical audit across all accounts.
8. **Automated Unit Tests:** `services/billing/tests/test_ledger.py` (8/8 tests passing, integrated into `setup/lab.py`).

---

## 19. OpenAI-Compatible API Streaming Gateway

### Architecture & Capabilities
Implemented in `services/gateway/server.py` as an edge compatibility proxy:
1. **Drop-in OpenAI SDK Compatibility:** Implements `/v1/chat/completions`, `/v1/models`, and `/v1/billing/balance` supporting standard OpenAI Python, TypeScript, and cURL requests.
2. **Server-Sent Events (SSE) Streaming:** Emits real-time token chunks (`data: {"object": "chat.completion.chunk", ...}`) with clean `[DONE]` termination.
3. **Automated Metering & Ledger Integration:** Directly invokes `Ledger.record_job_execution(...)` upon completion, deducting micro-units from customer prepaid balances and crediting provider accounts.
4. **Fail-Closed Quota Check:** Rejects requests with HTTP 402 `insufficient_quota` if customer balances are exhausted.
5. **Automated Unit Tests:** `services/gateway/tests/test_gateway_server.py` (6/6 tests passing, integrated into `setup/lab.py` - total 13 suites, 300+ tests passing 100% on Windows and Linux).

---

## 20. Multi-GPU Scheduler & Heterogeneous Mining Rig Placement

### Architecture & Layer Sharding Math
Implemented in `services/scheduler/multi_gpu_planner.py`:
1. **Multi-GPU Aggregate VRAM Pooling:** Seamlessly pools arbitrary homogeneous and heterogeneous GPUs (e.g. 5x 8GB = 40GB, 8x RTX 3070 = 64GB, mixed AMD RX 580/590 + NVIDIA RTX 3060/3070/3080).
2. **Proportional Layer Offloading:** Splits large model layers (e.g. 64 layers for 32B models, 80 layers for 70B models) based on individual GPU VRAM budgets with KV-cache headroom validation.
3. **Contiguous Sharding Invariant:** Enforces $\text{layer\_end}_{i} == \text{layer\_start}_{i+1}$ and exact total layer coverage ($0 \le l < L$).
4. **Automated Unit Tests:** `services/scheduler/tests/test_multi_gpu_planner.py` (5/5 tests passing 100% on Windows and Linux).

---

## 21. Stripe Checkout & Automated Webhook Ingestion

### Architecture & Capabilities
Implemented in `services/billing/stripe_integration.py`:
1. **Real Stripe Checkout Path:** `StripePaymentService.create_checkout_session(...)` calls the official Stripe Python SDK (`stripe.checkout.Session.create`) when configured with `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, a `StripeSessionStore`, and the `stripe>=15,<16` package. It no longer fabricates live Checkout URLs.
2. **Server-Side Reconciliation Metadata:** Checkout Sessions carry `client_reference_id`, `metadata`, and `payment_intent_data.metadata` with the internal customer account and exact micro-unit amount. `StripeSessionStore` persists session/customer/payment-intent IDs for reconciliation.
3. **Signed Raw Webhook Processing:** `process_webhook_payload(...)` requires the unmodified raw Stripe request body plus `Stripe-Signature` and verifies through Stripe's webhook construction path before crediting the ledger. Direct parsed JSON webhook crediting is rejected unless tests explicitly mark an event trusted.
4. **Fail-Closed Live Configuration:** If live Stripe env is absent, Checkout fails instead of issuing fake payment URLs. If `STRIPE_API_KEY` is set but the SDK, webhook secret, or durable session store is missing, live configuration fails closed.
5. **Automated Unit Tests:** `services/billing/tests/test_stripe_integration.py` covers Checkout parameters, durable session records, signed webhook deposit, duplicate idempotency, missing config, untrusted direct-event rejection, and invalid signature rejection.

---

## 22. Windows Desktop Provider Tray Application

### Architecture & Features
Implemented in `tools/appliance/windows_tray_app.py`:
1. **Lightweight Native Desktop UI:** Zero heavy framework dependencies (pure Python Tkinter + ttk dark theme).
2. **Real-Time Hardware Auto-Detection:** Automatically scans GPU matrix (NVIDIA CUDA / AMD Vulkan) displaying device model, VRAM allocation, and operating temperatures.
3. **1-Click Compute Control:** Instant Online / Idle toggle with live token counting and continuous micro-credit passive earnings display.

---

## 23. Mutual TLS (mTLS) Peer-to-Peer Encrypted Transport (ADR 0003)

### Architecture & Capabilities
Implemented in `runtime/network/mesh_transport.py`:
1. **Zero-Configuration Ephemeral Credentials:** Automatically provisions TLS 1.3 certificates bound to node identities (`generate_node_tls_credentials`).
2. **Mutual Peer Authentication:** Coordinator and provider rigs authenticate bidirectionally using RSA/Ed25519-pinned certificates.
3. **Transparent TCP Tunneling:** `MeshTunnelServer` and `MeshTunnelClient` encapsulate RPC streams over TLS, eliminating manual SSH key management.
4. **Automated Unit Tests:** `runtime/network/tests/test_mesh_transport.py` (2/2 tests passing, total 14 network tests).

---

## 24. Debian Live NodeOS Image Builder Automation

### Architecture & Distribution Pipeline
Implemented in `deploy/appliance/debian_live_builder.py`:
1. **Turnkey Live Image Configuration:** Configures Debian 13 (Trixie) live-build with kernel 6.x and non-free firmware packages (`firmware-amd-graphics`, `firmware-misc-nonfree`).
2. **Dual-Stack GPU Driver Bundle:** Pre-packages Mesa RADV Vulkan and NVIDIA proprietary drivers.
3. **FAT32 USB Boot Autostart:** Automatically reads `/boot/computemesh.env` on boot and starts `computemesh-appliance.service`.
4. **Automated Unit Tests:** `deploy/appliance/tests/test_debian_live_builder.py` (2/2 tests passing, total 14 suites, 310+ tests passing 100% on Windows and Linux).

---

## 25. Autonomous Node Health & Dynamic Failover Engine

### Architecture & Capabilities
Implemented in `services/scheduler/health_monitor.py`:
1. **Real-Time Heartbeat & Thermal Telemetry:** Monitors continuous node heartbeats, VRAM metrics, and GPU core temperatures (marks nodes `DEGRADED` if $T > 85^\circ\text{C}$).
2. **Exponential Penalty & Flapping Dampening:** Accumulates penalty scores for unstable nodes and decays penalties across continuous healthy operation.
3. **Automated Layer Evacuation & Re-Sharding:** `failover_rebalance(...)` automatically recalculates shard boundaries for active neural networks when worker nodes fail or disconnect, preserving client inference sessions without crashing.
4. **Automated Unit Tests:** `services/scheduler/tests/test_health_monitor.py` (6/6 tests passing, total 48 scheduler tests).

---

## 26. Prometheus & OpenMetrics Telemetry Exporter

### Architecture & Observability
Implemented in `services/gateway/metrics_exporter.py`:
1. **OpenMetrics / Prometheus Endpoint:** Serves `GET /metrics` and `GET /v1/metrics` in standard OpenMetrics text format.
2. **Infrastructure Telemetry Gauges:** Exposes `computemesh_active_nodes`, `computemesh_active_gpus`, and `computemesh_total_vram_bytes`.
3. **Inference & Billing Counters:** Meters `computemesh_requests_total{model, status}`, `computemesh_tokens_generated_total{model}`, `computemesh_tokens_prompt_total{model}`, and `computemesh_invoiced_usd_total`.
4. **Automated Unit Tests:** `services/gateway/tests/test_gateway_server.py` (8/8 tests passing, total 15 suites, 325+ tests passing 100% on Windows and Linux).

---

## 27. Web3 & On-Chain Crypto Payment Ingestion Engine

### Architecture & Capabilities
Implemented in `services/billing/crypto_payments.py` as a simulated ingestion adapter:
1. **Mock Multi-Chain Stablecoin Ingestion:** Supports USDT/USDC labels on Ethereum, Polygon, Arbitrum, Base and BSC only after a caller supplies an already-confirmed transaction. It does not poll RPC endpoints, subscribe to logs, verify receipts, or generate controlled deposit wallets.
2. **Double-Entry Ledger Integration:** Programmatically supplied transaction hashes can trigger atomic credit top-ups to customer balance accounts.
3. **Automated Unit Tests:** `services/billing/tests/test_crypto_payments.py` covers deterministic address mapping, duplicate tx idempotency, minimum deposits and unsupported networks.

---

## 28. Cryptographic Release Signing & Multi-Platform Auto-Updater (Ed25519)

### Architecture & Capabilities
Implemented in `tools/security/release_signer.py`, `tools/security/signing_keys.py`, `tools/security/ed25519_verify.py`, and `services/updater/auto_updater.py`:
1. **Master Ed25519 Signing Pipeline:** The private signing key (`computemesh_release_signing_private.key`) is generated and secured exclusively on `\\diskstation\Dani\ComputeMesh`.
2. **Zero-Dependency RFC 8032 Verifier:** Standard Python library Ed25519 verification without requiring external C libraries or compiled wheels (`tools/security/ed25519_verify.py`).
3. **Cryptographic Manifest Verification:** All client nodes (Windows, Linux, NodeOS) verify the digital Ed25519 signature of `version.json` and validate the SHA-256 binary hash before downloading or executing any update. Tampered bytes trigger immediate execution rejection (`SignatureVerificationError`).
4. **First-Launch Opt-In:** Windows App, Linux Desktop GUI, and `install.sh` explicitly prompt the user during installation to enable automated signed updates.
5. **Linux Desktop Provider GUI:** Standalone native Linux GUI (`tools/appliance/linux_tray_app.py`) with multi-GPU detection, system tray, and `.desktop` autostart.
6. **Automated Unit Tests:** `services/updater/tests/test_auto_updater.py` (100% passing).

---

## 29. Physical Miner Rig Monitor Remote Access Banner & Network IP Auto-Detection

### Architecture & Capabilities
Implemented in `services/appliance_dashboard/server.py` and `tools/appliance/console_banner.py`:
1. **Prominent Monitor Remote Access Banner:** Kiosk dashboard and Linux TTY / `/etc/issue` prominently display all assigned network IP addresses (`http://<IP>:8080/` and `http://<IP>:8080/#config`) in high-contrast glowing typography visible across the room.
2. **Scanable Smartphone QR-Code:** Renders an instant QR-code directly on the physical monitor so miners without a keyboard or mouse can point their phone camera at the screen to immediately open the dashboard and connect MetaMask.
3. **One-Click OS Upgrade & OTA Update:** Dedicated dashboard action buttons for `Check & Apply Signed Update (Ed25519)` and `OS System Upgrade (Debian apt-get update & upgrade)`.
4. **Live Artifacts:** Hybrid `.iso`, compressed `.img.xz`, Windows `.exe`, and Linux `.tar.gz` built, verified, and hosted on production server.

---

## 30. Mobile-First Responsive Redesign & Web3 Mobile Deep-Linking

### Architecture & Capabilities
Implemented in `services/appliance_dashboard/server.py`:
1. **Mobile Viewport & Touch Ergonomics:** `<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">`, zero horizontal blowout (`max-width: 100vw; overflow-x: hidden`), 48px touch targets, and full-width buttons.
2. **Smart Remote Client Detection:** Automatically hides the QR-code box on smartphones and remote laptops (`isRemoteClient = true`), keeping screen space focused on GPU metrics and payout settings.
3. **Instant Clipboard Paste:** Dedicated `[ 📋 Einfügen ]` button that reads `0x...` Ethereum/Polygon addresses directly from clipboard into the wallet form with automatic persistence.
4. **MetaMask Mobile Deep-Link:** `[ 🦊 Connect MetaMask ]` on smartphones opens `https://metamask.app.link/dapp/...` to launch the MetaMask mobile app with injected Web3 browser.
5. **Live Status Alerts:** Instant popup and toast confirmation (`✓ Alles ist auf dem neuesten Stand`) when the node is already running the latest signed version.

---

## 31. Windows Standalone Executable & Installer Packaging

### Architecture & Distribution Pipeline
Implemented in `deploy/windows/build_installer.py`:
1. **Zero-Dependency Executable Packaging:** Bundles the Windows Desktop Provider Agent GUI into a standalone `ComputeMesh-Setup-x64.exe` package (31.5 MB).
2. **Cryptographic Integrity & SHA-256 Hashing:** Automatically verifies payload hashes and provisions `/downloads/ComputeMesh-Setup-x64.exe` on the public web server.
3. **Automated Unit Tests:** `deploy/windows/tests/test_build_installer.py` (100% passing across all platforms).

---

## 32. Continuous Background Auto-Updater Daemon & Live Server Service

### Architecture & Capabilities
Implemented in `services/updater/auto_updater.py` and `/etc/systemd/system/computemesh-autoupdate.service`:
1. **Periodic Background Polling Daemon:** Runs continuously on Linux servers (`--daemon --interval 300`) checking for new cryptographic Ed25519-signed releases against `https://computemesh.inetconnector.com/updates/version.json`.
2. **Automated Verification & Zero-Downtime Reload:** Automatically verifies SHA-256 payload integrity and Ed25519 signature before extracting packages and triggering service reloads (`computemesh-appliance.service` and `computemesh-gateway.service`).
3. **Live Systemd Deployment:** Registered and active as an enabled systemd daemon (`computemesh-autoupdate.service`) on production server `89.58.11.237`.

---

## 33. Desktop GUI Hardening, URL Routing Fix & MetaMask 2-Way Sync

### Architecture & Capabilities
1. **Zero Console Window Flashes (`CREATE_NO_WINDOW`):** Set `creationflags=0x08000000` on all Windows hardware detection and telemetry subprocesses (`nvidia-smi`, `powershell`, `wmic`).
2. **Centered Window Spawning:** Dynamically calculates screen geometry to spawn the application in the exact visual center of the user's display.
3. **Query Parameter Routing Fix (`urllib.parse`):** Stripped query strings from handler path routing in `server.py` so URLs like `/?action=metamask#config` return HTTP 200 instead of 404.
4. **Instant MetaMask 2-Way Synchronization:** Web dashboard triggers account selection popup on `action=metamask`, automatically saves selected wallet address, and desktop app reflects the address via live background telemetry loop.
5. **Standalone Bundle Packaging:** Fully bundled `services`, `tools`, and `portal` into `ComputeMesh-Setup-x64.exe` with `sys._MEIPASS` pathing and verified startup.

---

## 34. Current Main Snapshot From 2026-08-24

### Repository Hygiene
1. **Clean branch topology:** After pruning, only `main` / `origin/main` exists. All historical M1 feature/debug branches mentioned in older handoffs are gone.
2. **No active PR queue:** `gh pr list --state open` returned an empty list.
3. **No GitHub Actions at HEAD:** `.github` is absent, `git ls-tree -r --name-only HEAD -- .github` returned no files, and `gh workflow list --all` returned no workflows. There are no obsolete Actions to delete from the current tree.
4. **Working tree status before editing this file:** `## main...origin/main`, with no staged, unstaged, or untracked files.

### Latest Merged Behavior
1. **Network capacity telemetry:** The dashboard and Windows/Linux provider clients display local and global compute capacity using TFLOPS and VRAM summaries. Current global values in `services/appliance_dashboard/server.py` remain static/demo defaults (`2840.5 TFLOPS`, `3650.0 GB`) until connected to authenticated registry data.
2. **Configurable operator fee:** `services/billing/ledger.py` now defaults to `DEFAULT_NETWORK_FEE_BPS = 2500` (25.00%) and accepts `COMPUTEMESH_OPERATOR_FEE_BPS` plus `COMPUTEMESH_OPERATOR_TREASURY_WALLET`. Operator revenue accumulates in `revenue:network_fee`; `create_operator_treasury_payout(...)` emits the treasury payout summary.
3. **Operator monetization guide:** `docs/MONETIZATION_GUIDE.md` documents the current 25% operator-margin default, env/config keys, Stripe-first payment policy, and ledger-only settlement path.

### Verification During This Handoff Update
1. Ran repository status and topology checks only: `git status --short --branch`, `git rev-parse HEAD`, `git log -1`, `git fetch --prune`, `git branch --all --verbose --no-abbrev`, `git ls-remote --heads origin`, `gh pr list --state open`, `gh workflow list --all`, and `.github` tree checks.
2. Did **not** run the Python/unit/integration test suites during this documentation-only cleanup.
3. `README.md` / `README.de.md` were read for context but intentionally not changed; this update corrects maintainer handoff state rather than public project positioning.

### Live Server And Miner Access Check
1. **Webserver SSH:** `ssh -o BatchMode=yes supersrv-trixie ...` succeeds as `root` on `v2202606372671474589.supersrv.de` (`89.58.11.237`, Debian 13, kernel `6.12.94+deb13-amd64`).
2. **Webserver repo:** `/root/ComputeMesh` is clean on `main...origin/main` at `e2612d2` after `git fetch --prune`, `git pull --ff-only origin main`, and webroot refresh on 2026-08-24 09:35 CEST.
3. **Webserver services:** after redeployment at 2026-08-24 09:35 CEST, `computemesh-autoupdate.service` and `computemesh-gateway.service` are active/running. `systemctl show computemesh-autoupdate.service -p ExecStart` reports `/root/ComputeMesh/.venv/bin/python services/updater/auto_updater.py --daemon --interval 300 --version 1.2.9`. Gateway admin route `GET /v1/admin/server_status` reports `status: online`, `version: 1.2.9`, `git_commit: e2612d2`, branch `main`.
4. **Hosted artifacts:** live `https://computemesh.inetconnector.com/updates/version.json` reports `version = 1.2.9` with platforms `installer-script`, `linux-x64`, `nodeos-img`, `nodeos-iso`, and `windows-x64`. Webroot hashes verified on the server: Windows `0b50f45500b3e711e53e609bc898fd73d741276e41893c4c1362fdcaa7859517` (35,250,289 bytes), Linux `35d52c496116e8f34cbc01389e0445876cfa2424c5d54eb15f3883e9aa757821` (1,343,207 bytes), installer script `da40c753915808e51a23f6079b402f557c4aefce7c18b445f36f11db09bb5acf`; preserved NodeOS ISO `32fa381346305a8e60ded2b7b3f152fe3104650e72cc55d3a6e2fa8ba8058499`, NodeOS IMG `271c33516ebfd014507081e1e5baf145f159c7b49e1ea1ec02d0a20fff78c4e1`. `tools.security.release_signer.verify_manifest(Path("portal/updates/version.json"))` returned `True` on the server.
5. **RPC worker process:** Webserver has `ggml-rpc-server` from `llama.cpp/b10549-cpu-x86_64` listening only on `127.0.0.1:50052`; this is not public.
6. **Local miner discovery:** mDNS resolves `computemesh-nodeos.local` to `192.168.1.27` and `192.168.1.91`. Port scan found `192.168.1.27` with SSH/22 and dashboard/8080; `192.168.1.91` did not respond on SSH/8080 during this check.
7. **Miner dashboard:** `http://192.168.1.27:8080/api/status` reports node `cm-inference-node-01`, interface `enp2s0`, two detected GPUs and 16 GiB total VRAM. The dashboard is reachable without SSH.
8. **Miner SSH:** `ssh -o BatchMode=yes root@192.168.1.27 ...` fails with `Permission denied (publickey,password)` using the currently available keys. SSH access is therefore not available non-interactively from this workstation.
9. **Miner update status:** before deployment, `http://192.168.1.27:8080/api/status` reported `software.current_version = "1.2.8"`. After the live manifest was updated, `/api/action/check_update` returned `update_available: true`, `version: 1.2.9`, `filename: computemesh-linux-x86_64.tar.gz`; `POST /api/action/apply_update` returned `{"status":"ok","message":"Updated to v1.2.9"}`; the later `/api/status` poll reports `software.current_version = "1.2.9"` and `/api/action/check_update` reports `update_available: false`.
10. **PC update status:** no local ComputeMesh/Provider Agent process was running during the 2026-08-24 09:36 CEST process check. The local Windows installer is rebuilt for `1.2.9` and signed in the manifest; `AutoUpdater(current_version="1.2.9").check_for_updates()` on the PC returned the live `1.2.9` Windows package with `is_newer = False`, so the PC-side updater sees no newer release.

### Release UI Update From 2026-08-24
1. **NodeOS web dashboard:** added live signed-release status text, `software.current_version` in `/api/status`, footer version display, and an update button that changes to `Update auf v<version> installieren` when the webserver manifest is newer.
2. **Windows/Linux provider apps:** bumped UI/runtime version to `1.2.9`, changed provider payout messaging to state MetaMask is only an address picker, and changed demo earnings math from 85% to the current 75% provider pool after the 25% operator fee.
3. **Portal and manifest:** updated public portal/AGB/privacy/status/i18n wording to state customer compute-credit payments run through Stripe and wallets are provider payout addresses only; rebuilt Windows and Linux artifacts; re-signed `portal/updates/version.json` as `1.2.9` with the existing official Ed25519 key while preserving the previously verified NodeOS ISO/IMG entries.
4. **Verification:** `python -m py_compile services/appliance_dashboard/server.py services/updater/auto_updater.py tools/appliance/windows_tray_app.py tools/appliance/linux_tray_app.py services/gateway/server.py tools/security/release_signer.py services/billing/ledger.py services/portal/server.py` passed; `python -m unittest services.updater.tests.test_auto_updater services.appliance_dashboard.tests.test_dashboard_server services.gateway.tests.test_gateway_server services.billing.tests.test_ledger services.portal.tests.test_portal_server deploy.windows.tests.test_build_installer -v` ran 29 tests successfully; `python -c "from pathlib import Path; from tools.security.release_signer import verify_manifest; print(verify_manifest(Path('portal/updates/version.json')))"` returned `True`; `git diff --check` reported only line-ending warnings.
5. **Build/distribution verification:** a fresh Windows verification build and Linux verification tarball were created under ignored `artifacts/release_verify*` directories on 2026-08-24. These build outputs are not byte-identical to the signed release artifacts because the current packaging embeds build-time metadata/timestamps; therefore the already signed and tagged `v1.2.9` artifacts remain the canonical distributable payloads until a future version bump.

## 35. Billing / MetaMask / Stripe Audit From 2026-08-24

### Verified Current Flow
1. **MetaMask on NodeOS/dashboard:** `services/appliance_dashboard/server.py` only calls the injected EIP-1193 provider to request/select `eth_accounts`, writes the first `0x...` address into `cfg-wallet`, and persists it through `/api/config` as `payout_address`. This is a provider/miner payout-address preference, not a customer payment, wallet ownership proof, SIWE login, token transfer, or on-chain settlement.
2. **Provider wallet persistence:** `tools/appliance/appliance_config.py` loads/saves `WALLET_PAYOUT_ADDRESS` / `PAYOUT_ADDRESS` plus `provider_account_id` to local system/user/boot config. There is no current registration handshake that binds this payout address to a gateway ledger provider account.
3. **Stripe customer top-up path:** `/v1/billing/checkout` now delegates to `StripePaymentService.create_checkout_session(...)`, which calls the official Stripe SDK when live config exists and otherwise fails closed. `/v1/billing/webhook` now passes the exact raw request body and `Stripe-Signature` to `process_webhook_payload(...)`; ledger crediting happens only after signature verification and a paid Checkout Session event. The service persists Stripe session/customer/payment-intent IDs through `COMPUTEMESH_STRIPE_SESSION_STORE` when configured.
4. **Direct test top-up path:** `/v1/billing/topup` no longer lets normal bearer tokens self-credit by default. It requires admin authentication unless `COMPUTEMESH_ALLOW_TEST_TOPUP=1` is deliberately set for local testing.
5. **Crypto customer top-up path:** `services/billing/crypto_payments.py` remains a simulated adapter only and is not the intended production purchase path. Product/UI/legal wording now states that real customer payments for compute credits must go through Stripe; MetaMask/wallets are for provider payout addresses only.
6. **Metering and 25% operator split:** On successful `/v1/chat/completions`, `GatewayHandler` calls `Ledger.record_job_execution(...)`. The ledger debits the customer, credits `revenue:network_fee` with `DEFAULT_NETWORK_FEE_BPS = 2500` (25%), and credits the remaining 75% to `provider:{provider_id}`. Current gateway provider mapping is hardcoded to `lab-mesh-default-rig`, so real miner/provider attribution is not wired.
7. **Operator payout destination:** `create_operator_treasury_payout(...)` can move the accumulated `revenue:network_fee` balance to `expense:settlements` and return a summary for `operator_treasury`, but no real wallet/bank transfer is executed. Live webserver env check showed `COMPUTEMESH_OPERATOR_TREASURY_WALLET`, `COMPUTEMESH_OPERATOR_FEE_BPS`, `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, and `COMPUTEMESH_ADMIN_KEY` all missing from the gateway unit environment.
8. **Persistence:** `GatewayHandler.ledger` now supports `COMPUTEMESH_GATEWAY_LEDGER_PATH`, but the live webserver still needs that path configured before real-money operation. Without it, customer balances, provider payables, and operator revenue remain process-memory only and are lost on gateway restart.

### Required Before Real Money Use
1. Configure live Stripe securely on the webserver: install `stripe>=15,<16`, set `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, and `COMPUTEMESH_STRIPE_SESSION_STORE`, register the public webhook endpoint in Stripe, and run a Stripe CLI/Dashboard test event against the deployed endpoint.
2. Configure `COMPUTEMESH_GATEWAY_LEDGER_PATH` or replace the current JSON persistence with a production database; never run real customer funds on the in-memory gateway ledger.
3. Add durable account storage and wire portal registration tokens to gateway accounts instead of keeping both stores separately in memory.
4. Add provider enrollment that binds node identity, provider ledger account, payout address, and wallet ownership proof. For EVM addresses, require a signed challenge before accepting or changing payout targets.
5. Keep crypto deposit ingestion disabled/non-public unless product policy changes. If stablecoin purchases are reintroduced later, they should be implemented through Stripe-supported crypto/stablecoin payment methods rather than ad-hoc MetaMask transfers.
6. Implement real payout execution: Stripe Connect/SEPA for bank payouts, optional Stripe-supported wallet/stablecoin payout where available, and a separate operator treasury payout executor. The operator's 25% must have an explicitly configured destination account before payout jobs can run.
7. Keep `/v1/billing/topup` disabled in production by leaving `COMPUTEMESH_ALLOW_TEST_TOPUP` unset and requiring admin authentication for any direct test credits.
8. User-facing text was corrected on 2026-08-24 to state: MetaMask is only for selecting provider payout addresses for earnings from contributed compute power; all real customer payments for compute credits run through Stripe. Files updated: `portal/index.html`, `portal/docs.html`, `portal/terms.html`, `portal/privacy.html`, `portal/status.html`, `portal/portal.js`, `services/appliance_dashboard/server.py`, `tools/appliance/windows_tray_app.py`, `tools/appliance/linux_tray_app.py`, `services/billing/README.md`, `README.md`, `README.de.md`, and `docs/MONETIZATION_GUIDE.md`.

### Verification During This Audit
1. `python -m unittest services.billing.tests.test_stripe_integration services.gateway.tests.test_gateway_server -v` ran 17 tests successfully on 2026-08-24 after the real Stripe integration path was added. These tests validate Stripe SDK call construction and signed webhook control flow with an injected fake Stripe client/verifier; they do not call Stripe's network API.
2. Official provider documentation checked during implementation: Stripe Checkout Sessions require server-side Session creation with `mode=payment`, `line_items`, `success_url`, and reconciliation fields such as `client_reference_id`/`metadata`; Stripe webhook verification requires the raw request body, the `Stripe-Signature` header, and the endpoint secret; MetaMask `eth_requestAccounts` only requests account access, while signing flows require separate signature RPC methods.
