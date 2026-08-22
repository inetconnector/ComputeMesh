# ComputeMesh State

**Last updated:** 2026-08-22 13:01 CEST  
**Phase:** M0 foundation + M1 engineering path through identity, evidence binding, GGUF manifests, two-node feasibility planning, evidence transfer/bundling, controlled llama.cpp RPC runtime, shared-run proof binding, one-command physical trial orchestration, and benchmark→runtime build binding. A real single-host Vulkan+RPC loopback attempt now reaches local baseline, RPC discovery and the ComputeMesh relay, but the relayed shared run fails during `server_start`. **No successful physical two-machine shared inference has yet been evidenced.**  
**Production services/runtime:** none  
**Public release:** none

This file is the **canonical context-free engineering handoff**. A new AI model with no access to prior chat history must be able to read `state.md`, inspect the referenced repository files/commits if necessary, and immediately continue the project safely without guessing what is merged, what is experimental, what has actually been measured, what failed, and what must happen next.

---

## 1. Repository truth

- repository: `inetconnector/ComputeMesh`
- canonical/default branch: `main`
- canonical merged **code baseline before this documentation-only handoff update**: `f822e7170882036834ee4a066ada95bd2117d2b9`
- this `state.md` update is documentation-only; no production/runtime behavior is intentionally changed by it
- ADR 0002 remains **Proposed** because a correct shared local+RPC runtime proof is still missing
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

### Current branch / PR topology at this handoff

The last verified repository branch search showed:

- `main` — canonical merged branch
- `m1/runtime-build-binding` — **no unique commits**, byte-identical to `main` when compared (`ahead 0`, `behind 0`); stale merged ref
- `m1/shared-run-evidence` — **no unique commits**, `ahead 0`, `behind 40`; stale merged ref
- `m1/shared-trial-runner` — **no unique commits**, `ahead 0`, `behind 11`; stale merged ref
- `test/real-llama-rpc-loopback` — active temporary integration/debug branch, Draft PR #14; last recorded head `645e1e51b726b900f4cf35712aedf2319f062d35`; its net diff against the code baseline is intentionally limited to `.github/workflows/temporary-real-llama-rpc-loopback.yml` and `temporary-real-rpc-loopback-result.json`
- `docs/state-current-handoff` — temporary documentation-only branch used to publish this handoff; after fast-forward it should contain no durable code change beyond `state.md` and is safe to delete if still visible

**PR #14 must not be merged as-is.** It is an execution/debug vehicle. Any durable fix discovered there must be implemented/reviewed on a normal feature branch, fully validated, documented here, and merged without its temporary workflow/result files.

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

Execution/debug artifacts live only on temporary Draft PR #14.

### Exact ingredients

- temporary branch: `test/real-llama-rpc-loopback`
- Draft PR: #14
- last recorded result head: `645e1e51b726b900f4cf35712aedf2319f062d35`
- upstream source tag built: llama.cpp `b10580`
- correct RPC CMake target: `ggml-rpc-server`
- runtime self-report captured by baseline: `version: 0.2.0-dev (build 1, commit 54ee5ee)`, GNU 13.3.0, Linux x86_64
- Ubuntu 24.04 GitHub runner with Mesa llvmpipe
- environment aligned with upstream headless Vulkan testing:
  - `GGML_VK_VISIBLE_DEVICES=0`
  - `GGML_VK_DISABLE_F16=1`
  - `GGML_VK_DISABLE_COOPMAT=1`
- Vulkan enumeration: `Vulkan0 = llvmpipe (LLVM 20.1.8, 256 bits)`
- RPC server: `Starting RPC server v5.1.0`, endpoint `127.0.0.1:50052`, device `Vulkan0`
- model: `SmolLM2-135M-Instruct-Q4_K_M.gguf`
- model size: **105454144 bytes**
- model SHA-256: **`ed5fa30c487b282ec156c29062f1222e5c20875a944ac98289dbd242e947f747`**

### What succeeded

1. llama.cpp Vulkan + RPC source build completed with `llama-server` and `ggml-rpc-server`.
2. Local discovery exposed `Vulkan0`.
3. Direct RPC discovery against `127.0.0.1:50052` exposed both:
   - `Vulkan0`
   - `RPC0: 127.0.0.1:50052`
4. A real local baseline inference completed successfully on `Vulkan0`.

Baseline run:

- `run_id = llama-rpc-d0c95fa99a902227`
- `model_ready_ms = 18331.510482`
- `request_ms = 12441.638347`
- prompt: 14 tokens / 8886.915 ms / ~1.57535 tok/s
- predicted: 18 tokens / 3553.042 ms / ~4.78463 tok/s
- prompt/output/token correctness digests persisted; no raw prompt/output persisted

5. A zero-delay ComputeMesh measurement relay started:

- listen: `127.0.0.1:50053`
- target: `127.0.0.1:50052`
- termination: clean `eof`
- coordinator→worker: **42 bytes**
- worker→coordinator: **48 bytes**
- total forwarded: **90 bytes**
- `active_elapsed_ms = 51.300458`
- `total_elapsed_ms = 349.565246`

### What failed

The **relayed shared run did not reach model-ready/inference**.

`runtime.llama.rpc_spike run` failed with:

```text
phase: server_start
error_type: ConnectionResetError
message: [Errno 104] Connection reset by peer
run_id: llama-rpc-6dd71e2642b20c42
```

No successful shared result, no `comparison.json`, and no valid `shared_run_evidence.json` were produced.

The 90 relay bytes are only opaque RPC/control traffic from the failed startup path. They are **not activation-tensor bytes and not evidence of distributed model execution**.

### Leading blocker hypothesis — not yet proven

`runtime/network/tcp_relay.py` currently implements `run_relay_once(...)`, whose contract is explicitly **“Relay one TCP connection”**. It performs one `listener.accept()` and then exits after that connection completes.

During the real failed experiment, `ggml-rpc-server` logged multiple accepted/closed client connections, while the measurement relay completed after the first short 90-byte exchange.

The strongest current hypothesis is therefore:

> llama.cpp RPC startup uses multiple sequential TCP connections, but the current one-shot relay disappears after the first connection; a later connection then resets, producing the observed `ConnectionResetError` during `server_start`.

This is a **hypothesis**, not a verified root cause. Do not redesign the relay until the direct-without-relay A/B test below is run.

---

## 12. Current blockers / things that do not exist

### Immediate software blocker

- the real single-host shared local+RPC path currently resets in `server_start` when routed through the current one-connection measurement relay;
- the decisive direct-without-relay A/B experiment has not yet been recorded;
- therefore it is not yet known whether the failure is caused by relay connection lifecycle or by upstream llama.cpp b10580 shared server/device/split behavior.

### Physical-evidence blockers

Still missing:

- fresh trusted-private-LAN A→B network evidence using current embedded local/peer Lab IDs for the actual two target machines;
- matching current-profile llama prefill/decode on both target machines for the **same exact complete GGUF** and same concrete llama.cpp build identity;
- real worker evidence ZIP copied/imported on the physical coordinator;
- first real experiment bundle from fresh physical records;
- correct two-device local+RPC shared inference on the physical nodes;
- real target-machine llama.cpp-through-relay byte/timing evidence;
- physical `shared_run_evidence.json` bound from exact successful bundle/baseline/shared/relay artifacts.

### Security / production blockers

Still absent:

- authentication on TCP benchmark and upstream llama.cpp RPC socket;
- producer-signed/attested evidence provenance;
- authenticated evidence transfer;
- activation-tensor-specific transfer accounting;
- packet-level loss/reordering evidence;
- calibrated shared-runtime latency/speedup prediction or production scheduler ranking;
- schema-v1 multi-shard GGUF set identity/order contract;
- production provider-node app/service/installer;
- Gateway/API;
- production orchestrator network service/database adapter;
- authenticated/authorized provider-facing identity APIs;
- OS-protected private-key storage;
- active-session revocation fan-out;
- authenticated/encrypted ComputeMesh control/data transport;
- general authorization/rate/resource/abuse controls;
- hardware attestation or Sybil-proof physical-node identity;
- minimum production artifact/runtime/result/failure/heartbeat wire operations;
- production registry/verification/billing/telemetry/SDK/UI;
- signed production release/update system.

The ComputeMesh identity/session layer does **not** authenticate the benchmark or upstream RPC socket. Lab-ID self-report, ZIP transfer, relay, GGUF helper, bundle and planner do not change that.

---

## 13. ADR status

Accepted:

- ADR 0001 — repository bootstrap
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**

Still Proposed:

- ADR 0002 — M1 runtime baseline; harness/relay/transfer/bundle/planner/proof/trial machinery exists, but correct real shared proof does not
- ADR 0003 — control/data transport
- ADR 0004 — model/artifact identity; single complete GGUF facts are locally derived, but multi-shard identity/order and production distribution remain unresolved
- ADR 0006 — telemetry envelope
- ADR 0007 — ledger units

---

## 14. Exact next actions in order

### A. Immediate software diagnosis — do this first

1. Continue from Draft PR #14 evidence, but **do not merge PR #14** or its temporary workflow/result files.
2. Reproduce with the same real GGUF and source-built llama.cpp b10580 binaries.
3. Execute the exact shared local+RPC configuration **directly against `127.0.0.1:50052` with no `runtime/network/tcp_relay.py`**. Preserve bounded result/failure evidence. This is the decisive A/B test.
4. If direct local+RPC also fails:
   - debug the exact llama.cpp b10580 server/device/`tensor_split` startup semantics using discovered `Vulkan0` + `RPC0`;
   - do **not** blame or redesign the relay yet;
   - rerun until direct local+RPC either succeeds correctly or the upstream limitation is characterized.
5. If direct local+RPC succeeds:
   - instrument/confirm how many sequential/concurrent TCP connections llama.cpp RPC opens during startup and inference;
   - validate that the current one-shot relay lifecycle is the actual cause of the reset.
6. If multiple RPC connections are required, implement a **bounded multi-connection relay/session measurement design** on a normal feature branch, with:
   - explicit maximum connections;
   - bounded concurrency/queues/resources;
   - deterministic lifecycle/shutdown;
   - per-connection and aggregate opaque directional bytes/timing;
   - private-target restrictions preserved;
   - no payload persistence;
   - deliberate schema/proof updates rather than silent semantic changes.
7. Add regression/integration tests reproducing the observed real RPC connection lifecycle. Preserve appropriate single-connection fail-closed behavior where relevant.
8. Run the full Windows/Ubuntu matrix.
9. Repeat the real single-host experiment and require:
   - baseline success;
   - relayed shared local+RPC success;
   - exact correctness comparison;
   - coherent relay metrics;
   - valid bounded proof evidence.
10. Move only durable code/tests/docs to a normal feature branch; update `state.md` with exact results; remove all temporary workflow/result files; merge workflow-free; close PR #14; clean stale refs when tooling permits.

### B. Then perform the physical two-machine proof

11. Put the **same complete GGUF** on both physical target machines. Merge shard sets first if necessary.
12. Capture fresh current node profiles on both machines.
13. Run fresh llama-bench prefill/decode on both machines for the exact same GGUF/size using the same concrete llama.cpp build number/commit.
14. On the trusted private LAN, capture fresh A→B and B→A network measurements with current embedded Lab IDs; choose coordinator after reviewing directionality.
15. On worker B run `setup\EVIDENCE-EXPORT.cmd` or `bash setup/EVIDENCE-EXPORT.sh`; transfer the ZIP to A through a trusted local method.
16. On A generate the model manifest from the exact complete GGUF with `tools/benchmark/gguf_manifest.py`.
17. On A run `setup\BUILD-BUNDLE.cmd` or `bash setup/BUILD-BUNDLE.sh`; retain verified peer import + `experiment_bundle.json`; do not use legacy peer/layer assertions.
18. If bundle recommendation is not `shared_experiment`, fix the measured feasibility issue rather than forcing a split.
19. On worker B start `setup\SHARED-WORKER.cmd` or `bash setup/SHARED-WORKER.sh`; use the RPC binary from the same remembered llama.cpp build tree.
20. On coordinator A run `setup\SHARED-PROOF.cmd` or `bash setup/SHARED-PROOF.sh`, select the exact bundle/GGUF and B's private IP. Require model/freshness/build/device/RPC preflight and exact planner split.
21. Require a real `shared_run_evidence.json` with exact correctness and inspect relay byte/timing evidence. Do not promote ADR 0002 or scheduler performance claims from preflight/failed evidence.
22. After the unperturbed proof, run controlled delay/jitter/disconnect experiments separately; use controlled OS/network emulation if packet loss/reordering becomes material.
23. Accept, reject or supersede ADR 0002 from measured evidence.
24. Only then calibrate scheduler ranking from correct shared runtime instead of invented coefficients.
25. Bind only the minimum artifact/runtime/result/failure wire operations required by the winning path and continue toward reproducible correct two-node inference under ComputeMesh control.

Before any public authenticated node service, separately complete protected node-key storage, provider-authenticated identity APIs, active-session revocation fan-out, transport security, authorization and resource limits.

---

## 15. Claims that remain explicitly forbidden

Until new evidence changes this file, do **not** claim:

- successful physical two-machine distributed inference;
- successful relayed shared inference from the 2026-08-22 loopback test;
- that 90 relay bytes are activation tensors;
- that current peer Lab-ID self-report authenticates a node;
- that ZIP hashes/signatures exist beyond integrity hashing;
- production-grade RPC security;
- production scheduling or calibrated shared speedup;
- confidential compute;
- production provider-node readiness.
