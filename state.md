# ComputeMesh State

**Last updated:** 2026-08-22  
**Phase:** M0 foundation with M1 reference identity, controlled llama.cpp runtime/relay tooling, artifact-derived GGUF manifests, bounded two-machine Lab evidence transfer, fail-closed two-node evidence bundling, and deterministic two-node feasibility planning; real shared inference is not yet evidenced  
**Production services/runtime:** none  
**Public release:** none

This is the canonical engineering handoff. It records what is implemented, what has actually been measured, the current trust/evidence boundaries, and the next experimental steps.

## Repository baseline

- repository: `inetconnector/ComputeMesh`
- canonical/default branch: `main`
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
- node-session wire/readiness binding landed through `2f1f33b`
- M1 reference node identity landed through `d45406f`
- controlled llama.cpp RPC M1 spike harness landed through `3db6ef9`
- bounded TCP measurement relay landed through `206248a`
- deterministic M1 two-node feasibility planner landed through `6177218`
- network-peer/model-layer evidence binding landed through PR #6
- bounded GGUF-v3 inspection/model-manifest generation landed through PR #7
- fail-closed current experiment-evidence bundle landed through PR #8; `main` was `d461a2e7` before the current branch
- bounded two-machine Lab evidence export/import + bundle launchers are implemented in PR #10; cross-platform code/test validation run `32553699055` passed before this state bookkeeping

## What exists

### Cross-platform Lab Setup and measurements

Windows and Linux Lab Setup provide:

- stable random non-hostname Lab node IDs;
- machine-readable node inventory with monotonically versioned profile revisions;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- bounded GGUF-v3 metadata/model-manifest helper;
- bounded worker-evidence ZIP export and verified coordinator import;
- direct Windows/Linux launchers for evidence export and current experiment-bundle construction;
- ignored local evidence under `artifacts/lab/`;
- one test action that runs benchmark/model, orchestrator, protocol, identity, scheduler/bundle, llama-runtime, network-runtime, and setup suites.

This remains engineering/lab tooling, not a public provider-node installer.

### Network benchmark evidence binding

The TCP benchmark remains a trusted-private-LAN engineering protocol with **no application authentication or encryption**.

Current servers can receive their Lab Setup ID via `--node-id`; current clients can query that bounded self-report before measuring. New benchmark records can therefore contain:

- `conditions.local_node_id` — client Lab Setup ID;
- `conditions.peer_node_id` — server self-reported Lab Setup ID;
- `conditions.peer_identity_binding = unauthenticated_server_report_v1`.

Properties:

- IDs are bounded to 1..128 printable characters and at most 512 UTF-8 bytes in the benchmark implementation;
- `peer_node_id` and `peer_identity_binding` are schema-paired;
- `--expected-peer-node-id` can fail closed on a different/missing current peer report;
- legacy servers remain measurable when an expected peer is not required;
- malformed identity queries with declared payload bytes close the connection so unread bytes are never reinterpreted as a following frame; depending on TCP/OS timing the client may see the attempted error header or immediate EOF/reset;
- Lab Setup automatically passes its random Lab ID into server/client roles.

**Boundary:** `unauthenticated_server_report_v1` is traceability only. It is not ADR-0005 Ed25519/session identity and must not be treated as a production trust proof.

### Artifact-derived GGUF model manifests

`model_manifest.schema.json` accepts optional `layer_count`; the placement planner prefers it and records `layer_count_source = model_manifest_v1`. Legacy explicit caller layer count remains supported only by the direct placement compatibility path.

`tools/benchmark/gguf_manifest.py` can build the current single-artifact manifest from a local little-endian GGUF v3 file.

Artifact-derived facts:

- `general.architecture` → manifest `architecture`;
- `<architecture>.block_count` → manifest `layer_count`;
- known standardized `general.file_type` → quantization label when safely mapped;
- `general.name`, `general.version`, `general.license`, `general.license.link` when present;
- exact local `size_bytes`;
- streaming SHA-256 digest.

The reader is bounded, reads metadata rather than tensor contents, does not execute model code, and never guesses missing model/version/license/quantization semantics or partitioning permission.

Current llama.cpp split metadata is recognized as the complete trio `split.no`, `split.count`, and `split.tensors.count`. Later non-primary shards can lack ordinary model metadata and are identified explicitly.

**Schema-v1 split boundary:** `split.count > 1` is inspectable but manifest generation is refused. One shard's digest/size is not the whole model and schema v1 does not yet encode shard membership/order strongly enough. Merge the full shard set to one GGUF first. `split.count == 1` remains buildable.

### Bounded M1 Lab evidence transfer

`setup/evidence_transfer.py` is the local transfer layer for the physical two-computer experiment. Export/import deliberately use only the Python standard library; scheduler/JSON-schema dependencies are loaded only when building the placement bundle.

Worker export invariants:

1. scan only bounded `*.json` below the configured node's `artifacts/lab/<node-id>/` tree;
2. export only recognized node-profile and benchmark JSON; unknown JSON is ignored, while profile/benchmark-shaped JSON with a wrong top-level contract fails closed;
3. require all captured profiles to refer to the configured node ID and require the configured profile revision to equal the newest captured revision;
4. exclude GGUF weights, llama.cpp binaries/runtime downloads, `artifacts/lab/config.json`, remembered local paths, and arbitrary files;
5. reject evidence-file symlinks;
6. bound evidence-file count, individual JSON size, total uncompressed bytes, ZIP size, and export-manifest size;
7. record each file in `computemesh-lab-export.json` by cross-platform-safe relative path, exact byte size, and SHA-256;
8. use fixed ZIP entry metadata rather than source mtimes/permissions so source filesystem metadata is not leaked;
9. derive deterministic `export_id = lab-export-<16hex>` from node ID, profile revision, and exact file path/size/hash records; `created_at` is observational metadata and is not part of evidence identity.

Coordinator import invariants:

1. reject archive symlinks, malformed/oversized ZIPs, encrypted entries, directory entries, ZIP symlinks, traversal/unsafe paths, duplicate names, unexpected members, and declared-size conflicts;
2. require the archive member set to match the manifest exactly;
3. stream every extracted file through exact byte-count and SHA-256 validation;
4. extract into a temporary directory and publish only by atomic rename after successful verification;
5. on re-import, revalidate the existing manifest/tree/hashes instead of trusting prior local files;
6. allow a repeated export of unchanged evidence to reuse the same import identity even if the later ZIP has a different observational `created_at`;
7. reject a tampered existing import.

Direct user-facing launchers:

- Windows worker export: `setup\EVIDENCE-EXPORT.cmd`;
- Windows coordinator bundle: `setup\BUILD-BUNDLE.cmd`;
- Linux worker export: `bash setup/EVIDENCE-EXPORT.sh`;
- Linux coordinator bundle: `bash setup/BUILD-BUNDLE.sh`.

The bundle launchers import/verify the peer ZIP and pass its evidence root plus the local coordinator tree and exact model manifest into the strict current experiment-bundle builder. Windows uses file pickers. Linux prompts for the paths. If `jsonschema` is not already in the repository-local `.venv`, only the bundle step installs that small dependency.

The transfer hashes are copy/integrity evidence, **not producer authentication, signatures, node identity proof, or hardware attestation**.

### Fail-closed M1 experiment evidence bundle

`services/scheduler/evidence_bundle.py` is the current engineering preparation layer in front of the placement planner. It consumes:

- one explicit coordinator evidence root;
- one explicit worker evidence root;
- one model manifest;
- optional evidence **selectors** only (`artifact_digest`, role node IDs, benchmark model basename, network run ID).

The current bundle path intentionally has **no caller peer-ID fallback and no caller layer-count fallback**.

Discovery/selection invariants:

1. anything that looks like a node profile or benchmark must validate against its repository schema or discovery aborts;
2. require one node identity per role unless explicitly disambiguated;
3. choose the highest profile revision and reject conflicting documents at that revision;
4. require `model_manifest.layer_count` and an exact selected manifest artifact;
5. llama prefill/decode evidence must match selected profile revision, exact artifact size, and must not predate that profile;
6. coordinator and worker must share one complete model basename (or caller selects one of multiple complete matches explicitly);
7. newest matching runs are selected only when uniquely newest; equally recent distinct candidates fail rather than being chosen nondeterministically;
8. network evidence must be coordinator→worker, match coordinator profile revision, carry embedded `local_node_id = coordinator` and `peer_node_id = worker`, and not predate the coordinator profile;
9. `build_placement_decision` is invoked without legacy peer/layer arguments;
10. a `caller_asserted_v1` network binding cannot produce a current bundle.

Output contract: `services/scheduler/experiment_bundle.schema.json`.

The output contains deterministic `bundle_id`, model/node/network provenance, safe source basenames, SHA-256 of every selected source JSON, run/node/profile/model identity, and the fully validated placement decision. Absolute local paths are not emitted and provenance source records reject unknown properties.

### Durable control/orchestration foundation

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

Current strict session wire subset:

- `NodeHello`;
- `NodeAuthenticate`;
- `CapabilityNegotiation`;
- `NodeProfileUpdate`;
- `BenchmarkReport`;
- `DrainRequest`.

Session semantics include mandatory injected authentication, protocol-version negotiation, authenticated actor binding, optimistic revisions, exact replay/request-ID conflict handling, capability intersection, profile/revision binding, benchmark readiness policy, and external termination for revocation/incident signals.

ADR 0005 is accepted only for the **narrow M1 reference implementation**. Authentication method: `computemesh-ed25519-v1`.

The Ed25519 proof binds session ID, per-session challenge, stable node ID, key ID, negotiated protocol version, proof issue/expiry time, and canonical accepted `NodeHello` semantics.

`services/identity/` provides a SQLite reference registry with stable random node IDs, one-time hashed enrollment tokens, public Ed25519 keys only, same-token/same-key idempotency, conflict rejection, key rotation, monotonic key/node revocation, and restart persistence. Existing authenticated sessions still require external revocation fan-out.

### Deterministic M1 two-node placement planner

`services/scheduler/placement.py` is an experiment **feasibility planner**, not a production scheduler/performance oracle.

It validates current coordinator/worker profiles, model manifest/artifact, four llama-bench records and coordinator→worker TCP evidence. Manifest `layer_count` and embedded network IDs are preferred; caller peer/layer values exist only in the direct legacy compatibility CLI and are excluded by the current bundle path.

Other hard bindings include exact profile revisions, one exact model basename/size across all four llama benchmarks, `contiguous_layers` manifest permission, stale/future/draining constraints, provider memory fraction, and conservative selected-device memory budgets.

Shared-memory approximation:

- default 10% model-size fixed coordinator overhead;
- remaining bytes spread uniformly over resolved layer count;
- at least one layer must fit each node;
- ranges are contiguous/non-overlapping and cover `[0, layer_count)`;
- layer counts become relative `tensor_split` experiment weights.

Recommendation modes are `shared_experiment`, `local_only`, and `no_plan`. Every decision sets `production_scheduling = false`.

Until a correct measured shared runtime exists:

```text
performance_evidence.status = insufficient_shared_runtime_evidence
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

No formula turns independent node/network benchmarks into fabricated shared speedup.

### Controlled llama.cpp M1 runtime experiment

`runtime/llama/rpc_spike.py` remains the first executable shared-runtime research harness. It does not make upstream llama.cpp RPC the ComputeMesh node protocol.

Guardrails include literal loopback/RFC1918 RPC endpoints only, coordinator HTTP on `127.0.0.1`, `--offline`, explicit discovered devices, explicit `layer` split/tensor ratios, `--fit off`, disabled prompt/RPC cache surfaces for the first experiment, deterministic request settings, and no advanced tensor overrides in the baseline experiment.

Commands: `worker`, `discover`, `baseline`, `run`, `compare`.

Evidence records include model SHA-256/size, bounded llama.cpp version, topology/placement, model-ready/request timing, prefill/decode metrics and content digests without raw prompt/output persistence.

**Boundary:** no actual successful shared local+RPC two-machine inference artifact has yet been recorded. ADR 0002 remains Proposed.

### M1 TCP measurement relay

`runtime/network/tcp_relay.py` is a lab measurement instrument, not the production transport/security boundary.

It listens only on `127.0.0.1`, targets only literal loopback/RFC1918 IPv4, rejects DNS/public/IPv6/wildcard/link-local endpoints, uses bounded queues/backpressure, counts directional opaque TCP bytes, separates setup/active/total timing, supports deterministic userspace stream delay/jitter and deliberate disconnects, and persists content-free failure evidence.

The relay does not parse llama.cpp RPC framing. Byte totals include control/framing/data and are **not activation-tensor byte counts**. Stream delay/jitter are not packet emulation; packet loss/reordering remains a separate controlled OS/network experiment.

## Cross-platform validation for the transfer block

Code/test validation run **`32553699055`** passed on both supported development OS families. This run includes the transfer implementation, the repeated-export idempotency regression, dependency-light `python -S` Lab startup, Linux launcher syntax/routing and real Windows PowerShell parsing. Public README/setup/test documentation was synchronized immediately afterwards; a final full run on that documentation-complete branch state is performed before the temporary workflow is removed and `main` advances.

**Windows Server 2025 / Python 3.11.9:**

- Windows evidence PowerShell parse: **passed**;
- benchmark/model tooling: **32/32**;
- orchestrator: **34/34**;
- protocol: **66/66**;
- identity/integration: **13/13**;
- scheduler placement + evidence bundle: **36/36**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup/launcher/evidence transfer: **33/33**.

**Ubuntu 24.04 / Python 3.11.16:**

- benchmark/model tooling: **32/32**;
- orchestrator: **34/34**;
- protocol: **66/66**;
- identity/integration: **13/13**;
- scheduler placement + evidence bundle: **36/36**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup/launcher/evidence transfer: **33/33**.

Transfer-specific software coverage includes exclusion of arbitrary/GGUF files, path-free export manifests, newest-profile binding, exact member-set validation, changed-content/hash rejection, ZIP traversal/symlink rejection, idempotent and tamper-detecting re-import, repeated export with different `created_at`, dependency-light script startup, Windows/Unix launcher syntax/routing, and a complete synthetic worker-export → coordinator-import → current experiment-bundle round trip.

This is software/loopback/synthetic-evidence validation. It is **not** real two-machine shared-runtime or placement-performance evidence.

## Real target-machine evidence from 2026-08-21

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H-class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU detected.
- Windows/Linux direct setup/profile and earlier test flows passed on the physical targets.
- Windows → internet Linux engineering TCP benchmark with temporary source-limited firewall rule: RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s; rule removed afterwards.
- Windows CUDA llama.cpp with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`: prefill 2866.127 tok/s for 512 prompt tokens; decode 76.210 tok/s for 128 generated tokens.
- Linux CPU llama.cpp smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tok/s for 128 prompt tokens; decode 0.201 tok/s for 32 generated tokens.

The public-internet TCP measurement predates current embedded peer binding, is not trusted-private-LAN A↔B proof, and is not distributed inference. The historical llama benchmarks used different GGUFs/sizes, so they do **not** form a valid current two-node bundle and cannot be used as the first shared-runtime evidence set.

## What does not exist / current blockers

- fresh trusted-private-LAN A→B network evidence using current embedded local/peer Lab IDs for the actual two test nodes;
- matching current-profile llama prefill/decode on both nodes for the **same exact complete GGUF**;
- a real worker evidence ZIP copied to/imported by the physical coordinator;
- the first real experiment bundle built from those fresh physical-node records;
- an actual correct two-device local+RPC shared-inference artifact;
- real llama.cpp-through-relay byte/timing evidence on the target machines;
- authenticated identity on the TCP benchmark or upstream llama.cpp RPC socket;
- producer-signed/attested evidence provenance or authenticated evidence transfer;
- activation-tensor-specific transfer accounting;
- real-runtime delay/jitter/disconnect sensitivity evidence;
- packet-level loss/reordering evidence;
- calibrated shared-runtime latency/speedup prediction or production scheduler ranking;
- schema-v1 multi-shard GGUF artifact identity/order contract and complete-set manifest builder;
- production provider-node application/service/installer;
- Gateway/API;
- production orchestrator network service/database adapter;
- authenticated/authorized provider-facing identity APIs;
- OS-protected private-key storage in the node agent;
- active-session revocation fan-out;
- authenticated/encrypted ComputeMesh control/data transport;
- general authorization, rate/resource limits and abuse controls;
- hardware attestation or Sybil-proof physical-node identity;
- minimum artifact/runtime/result/failure/heartbeat wire operations for the selected M1 path;
- production registry/verification/billing/telemetry/SDK/UI;
- signed production release/update system.

The ComputeMesh identity/session layer does **not** authenticate the TCP benchmark or upstream llama.cpp RPC socket. Lab-ID self-report, transfer ZIP, relay, GGUF helper, evidence bundle and planner do not change that. Upstream RPC/benchmark remain trusted-private-lab-only. `confidential_compute` remains invalid without a concrete TEE/attestation design.

## ADR status

Accepted:

- ADR 0001 — repository bootstrap;
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**.

Still proposed:

- ADR 0002 — M1 runtime baseline; controlled llama.cpp RPC harness, relay, transfer/bundle path and conservative planner exist, but no real correct shared proof yet;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity; single-GGUF artifact facts are derived locally, but multi-shard identity/order and production distribution remain unresolved;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

## Next actions in order

1. Put the **same complete GGUF** on both physical target machines. If it is a llama.cpp shard set, merge all shards first.
2. Capture a fresh current node profile on both machines.
3. Run fresh llama-bench prefill/decode on both machines for that exact same GGUF and exact size.
4. On the trusted private LAN, capture fresh A→B and B→A network measurements with current embedded Lab IDs; choose A as coordinator after reviewing directionality.
5. On worker B, run `setup\EVIDENCE-EXPORT.cmd` or `bash setup/EVIDENCE-EXPORT.sh`; copy the resulting ZIP to A through a trusted local transfer method.
6. On A, generate the ComputeMesh model manifest from the exact same complete GGUF with `tools/benchmark/gguf_manifest.py` so digest, size, architecture and `layer_count` come from the artifact rather than manual entry.
7. On A, run `setup\BUILD-BUNDLE.cmd` or `bash setup/BUILD-BUNDLE.sh`; retain the verified peer import and resulting `experiment_bundle.json`. Do not use legacy peer/layer assertions.
8. Inspect the bundle's embedded hard constraints/recommendation. If it is not `shared_experiment`, fix the measured feasibility issue rather than forcing a split.
9. Use compatible current llama.cpp builds; run `runtime.llama.rpc_spike discover` and retain exact local/RPC device names.
10. Run deterministic local `baseline` on the coordinator.
11. Start a fresh local measurement relay and execute exactly the bundle/planner-selected explicit local+RPC layer split through it.
12. Run `compare`; require same model/prompt digests and exact token/output correctness before making a shared-inference claim.
13. Retain relay directional byte totals plus setup/active timing for that exact successful run.
14. Repeat controlled delay/jitter/disconnect experiments; use separate controlled OS/network emulation if packet loss/reordering becomes material.
15. Accept, reject or supersede ADR 0002 from measured evidence, then calibrate scheduler ranking from the correct shared result instead of invented coefficients.
16. Bind only the minimum artifact/runtime/result/failure messages required by the winning path and continue toward reproducible correct two-node inference under ComputeMesh control.

Before any public authenticated node service, separately complete protected node-key storage, provider-authenticated identity APIs, active-session revocation fan-out, transport security, authorization and resource limits.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
