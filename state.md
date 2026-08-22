# ComputeMesh State

**Last updated:** 2026-08-22  
**Phase:** M0 foundation with M1 reference identity, controlled llama.cpp runtime/relay tooling, artifact-derived GGUF manifests, fail-closed two-node evidence bundling, and deterministic two-node feasibility planning; real shared inference is not yet evidenced  
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
- bounded GGUF-v3 inspection/model-manifest generation landed through PR #7 (`main` at `81ef209f` before the current bundle branch)
- fail-closed current-evidence bundle implementation is in PR #8; final cross-platform code/schema/README validation run `32552215387` passed before merge

## What exists

### Cross-platform Lab Setup and measurements

Windows and Linux Lab Setup provide:

- stable random non-hostname Lab node IDs;
- machine-readable node inventory with monotonically versioned profile revisions;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- bounded GGUF-v3 metadata/model-manifest helper;
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

The reader is bounded (metadata count/bytes, key/string sizes, array items/depth), reads metadata rather than tensor contents, does not execute model code, and never guesses missing model/version/license/quantization semantics or partitioning permission.

Current llama.cpp split metadata is recognized as the complete trio:

- `split.no`;
- `split.count`;
- `split.tensors.count`.

Current upstream `gguf-split` keeps ordinary model metadata in primary shard `split.no = 0`; later shards can lack it. The helper identifies that condition explicitly.

**Schema-v1 split boundary:** `split.count > 1` is inspectable but manifest generation is refused. One shard's digest/size is not the whole model and schema v1 does not yet encode shard membership/order strongly enough. Merge the full shard set to one GGUF first. `split.count == 1` remains buildable.

### Fail-closed M1 experiment evidence bundle

`services/scheduler/evidence_bundle.py` is the current engineering preparation layer in front of the existing placement planner. It removes the manual eight-file wiring step for the first real two-node experiment.

Inputs:

- one explicit coordinator evidence root;
- one explicit worker evidence root;
- one model manifest;
- optional **selectors** only (`artifact_digest`, role node IDs, benchmark model basename, network run ID).

The current bundle path intentionally has **no caller peer-ID fallback and no caller layer-count fallback**.

Discovery/selection invariants:

1. scan only JSON below the two explicit roots; bound file count and JSON size; do not follow evidence-file symlinks;
2. anything that looks like a node profile or benchmark must validate against its repository schema or discovery aborts;
3. require one node identity per role unless explicitly disambiguated;
4. choose the highest profile revision and reject conflicting documents at that revision;
5. require `model_manifest.layer_count` and an exact selected manifest artifact;
6. llama prefill/decode evidence must match selected profile revision, exact artifact size, and must not predate that profile;
7. coordinator and worker must share one complete model basename (or caller selects one of multiple complete matches explicitly);
8. newest matching runs are selected only when uniquely newest; equally recent distinct candidates fail rather than being chosen nondeterministically;
9. network evidence must be coordinator→worker, match coordinator profile revision, carry embedded `local_node_id` = coordinator and `peer_node_id` = worker, and not predate the coordinator profile;
10. `build_placement_decision` is invoked without legacy peer/layer arguments;
11. a `caller_asserted_v1` network binding cannot produce a current bundle.

Output contract: `services/scheduler/experiment_bundle.schema.json`.

The output includes:

- deterministic `bundle_id` derived from exact source-document hashes plus placement identity;
- benchmark model basename;
- model/node/network source provenance;
- safe source **basenames only**;
- SHA-256 of every selected JSON document;
- run IDs, node IDs/revisions, model artifact identity/layer count;
- the fully validated placement decision.

Absolute local paths are not emitted, and source records reject unknown properties. The source hashes make the selected copied evidence set reproducible; they are **not** producer attestation or signatures.

Example:

```bash
python -m services.scheduler.evidence_bundle \
  --coordinator-root imported/node-a-lab \
  --worker-root imported/node-b-lab \
  --model-manifest artifacts/model.computemesh-model-manifest.json \
  --output artifacts/m1/experiment-bundle.json
```

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

It validates current coordinator/worker profiles, model manifest/artifact, four llama-bench records and coordinator→worker TCP evidence.

Evidence resolution:

- manifest `layer_count` is preferred and recorded as `model_manifest_v1`;
- embedded network local ID must equal coordinator;
- embedded network peer ID must equal worker;
- caller peer/layer values remain available only to the direct legacy compatibility CLI and may never conflict with embedded evidence;
- the new bundle path excludes those legacy fallbacks entirely.

Other hard bindings:

- llama benchmark type/revision must match the current profile;
- all four records must use one model basename and exact selected artifact size;
- manifest must permit `contiguous_layers`;
- stale/future-skewed/draining node states constrain candidates;
- provider memory fraction combines with conservative planner memory fraction;
- largest accelerator memory is used when available, otherwise currently available system RAM is the CPU fallback.

Shared-memory approximation:

- default 10% model-size fixed coordinator overhead;
- remaining bytes spread uniformly over resolved layer count;
- at least one layer must fit each node;
- layer ranges are contiguous/non-overlapping and cover `[0, layer_count)`;
- layer counts become relative `tensor_split` experiment weights.

Recommendation modes:

- `shared_experiment`;
- `local_only`;
- `no_plan`.

Every decision sets `production_scheduling = false`.

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

Commands:

- `worker`;
- `discover`;
- `baseline`;
- `run`;
- `compare`.

Evidence records include model SHA-256/size, bounded llama.cpp version, topology/placement, model-ready/request timing, prefill/decode metrics and content digests without raw prompt/output persistence.

**Boundary:** no actual successful shared local+RPC two-machine inference artifact has yet been recorded. ADR 0002 remains Proposed.

### M1 TCP measurement relay

`runtime/network/tcp_relay.py` is a lab measurement instrument, not the production transport/security boundary.

It listens only on `127.0.0.1`, targets only literal loopback/RFC1918 IPv4, rejects DNS/public/IPv6/wildcard/link-local endpoints, uses bounded queues/backpressure, counts directional opaque TCP bytes, separates setup/active/total timing, supports deterministic userspace stream delay/jitter and deliberate disconnects, and persists content-free failure evidence.

The relay does not parse llama.cpp RPC framing. Byte totals include control/framing/data and are **not activation-tensor byte counts**. Stream delay/jitter are not packet emulation; packet loss/reordering remains a separate controlled OS/network experiment.

An ultra-fast Windows loopback relay may start/end within one `time.monotonic()` tick, so `active_elapsed_ms == 0.0` is valid in that synthetic test. Exact echoed content/byte counts remain required; longer configured timing tests still enforce elapsed bounds.

## Latest cross-platform validation

Final current-evidence-bundle code/schema/public-README validation run: **`32552215387`**.

The tested branch state includes the strict provenance schema, rejection of caller-asserted binding from the current bundle, path-leak schema regression, and all public README changes. Only this `state.md` bookkeeping and temporary-workflow removal follow before `main` is advanced; no runtime/test code changes occur after the successful run.

**Windows Server 2025 / Python 3.11.9:**

- benchmark/model tooling: **32/32**;
- orchestrator: **34/34**;
- protocol: **66/66**;
- identity/integration: **13/13**;
- scheduler placement + evidence bundle: **36/36**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup: **21/21**.

**Ubuntu 24.04 / Python 3.11.16:**

- benchmark/model tooling: **32/32**;
- orchestrator: **34/34**;
- protocol: **66/66**;
- identity/integration: **13/13**;
- scheduler placement + evidence bundle: **36/36**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup: **21/21**.

Bundle-specific software coverage includes highest-profile selection, old-revision filtering, pre-profile timestamp rejection, same-artifact-size/model-name binding, multiple-node/model disambiguation, equal-latest ambiguity rejection, correct network direction/embedded IDs, legacy/caller binding rejection, corrupt evidence fail-closed behavior, deterministic source/decision identity, strict provenance-schema fields and absolute-path non-disclosure.

This is software/loopback/synthetic-evidence validation. It is **not** real two-machine shared-runtime or placement-performance evidence.

## Real target-machine evidence from 2026-08-21

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H-class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU detected.
- Windows/Linux direct setup/profile and earlier test flows passed on the physical targets.
- Windows → internet Linux engineering TCP benchmark with temporary source-limited firewall rule: RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s; rule removed afterwards.
- Windows CUDA llama.cpp with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`: prefill 2866.127 tok/s for 512 prompt tokens; decode 76.210 tok/s for 128 generated tokens.
- Linux CPU llama.cpp smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tok/s for 128 prompt tokens; decode 0.201 tok/s for 32 generated tokens.

The public-internet TCP measurement predates current embedded peer binding, is not trusted-private-LAN A↔B proof, and is not distributed inference. The historical llama benchmarks used different GGUFs/sizes, so they do not form a valid current two-node bundle.

## What does not exist / current blockers

- fresh trusted-private-LAN A→B network evidence using current embedded local/peer Lab IDs for the actual two test nodes;
- matching current-profile llama prefill/decode on both nodes for the **same exact complete GGUF**;
- the first real experiment bundle built from those fresh physical-node exports;
- an actual correct two-device local+RPC shared-inference artifact;
- real llama.cpp-through-relay byte/timing evidence on the target machines;
- authenticated identity on the TCP benchmark or upstream llama.cpp RPC socket;
- producer-signed/attested evidence bundle provenance or authenticated evidence transfer;
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

The ComputeMesh identity/session layer does **not** authenticate the TCP benchmark or upstream llama.cpp RPC socket. Lab-ID self-report, relay, GGUF helper, evidence bundle and planner do not change that. Upstream RPC/benchmark remain trusted-private-lab-only. `confidential_compute` remains invalid without a concrete TEE/attestation design.

## ADR status

Accepted:

- ADR 0001 — repository bootstrap;
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**.

Still proposed:

- ADR 0002 — M1 runtime baseline; controlled llama.cpp RPC harness, relay, evidence bundle and conservative planner exist, but no real correct shared proof yet;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity; single-GGUF artifact facts are now derived locally, but multi-shard identity/order and production distribution remain unresolved;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

## Next actions in order

1. On two machines on one trusted private LAN, capture fresh node profiles and current bound A→B (and preferably B→A for diagnostics) network measurements.
2. Put the **same complete GGUF** on both machines. If it is a llama.cpp shard set, merge all shards first.
3. Generate the ComputeMesh manifest from that exact GGUF with `tools/benchmark/gguf_manifest.py`; retain its SHA-256, exact size, architecture and `layer_count`.
4. Capture matching current-profile llama-bench prefill/decode evidence on both machines for that exact GGUF/size.
5. Copy/export the two Lab evidence trees plus the manifest to one analysis machine and run `services.scheduler.evidence_bundle`; do not use legacy peer/layer assertions.
6. Retain the resulting real bundle and inspect its embedded recommendation/hard constraints. If it is not `shared_experiment`, fix the measured feasibility issue rather than forcing a split.
7. On compatible current llama.cpp builds run `runtime.llama.rpc_spike discover` and retain exact local/RPC device names.
8. Run deterministic local `baseline` on the coordinator.
9. Start a fresh local measurement relay and execute exactly the bundle/planner-selected local+RPC layer split through it.
10. Run `compare`; require same model/prompt digests and exact token/output correctness before making a shared-inference claim.
11. Retain relay directional byte totals plus setup/active timing for that exact successful run.
12. Repeat controlled delay/jitter/disconnect experiments; use separate controlled OS/network emulation if packet loss/reordering becomes material.
13. Accept, reject or supersede ADR 0002 from measured evidence, then calibrate scheduler ranking from the correct shared result instead of invented coefficients.
14. Bind only the minimum artifact/runtime/result/failure messages required by the winning path and continue toward reproducible correct two-node inference under ComputeMesh control.

Before any public authenticated node service, separately complete protected node-key storage, provider-authenticated identity APIs, active-session revocation fan-out, transport security, authorization and resource limits.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
