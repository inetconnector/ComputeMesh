# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 foundation with M1 reference identity, controlled llama.cpp runtime/relay tooling, and a deterministic two-node experiment placement planner; real shared inference is not yet evidenced  
**Production services/runtime:** none  
**Public release:** none

This file records current engineering facts, evidence boundaries, and next actions.

## Repository baseline

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
- Windows Lab Setup: `72773df` + UX/UAC hardening `cfe39a8`
- Linux Lab Setup: `3c99457`
- real Windows/Linux target smoke/fix pass: `86ea6a7`
- node-session wire/readiness binding landed through `2f1f33b`
- M1 reference node identity landed through `d45406f`
- controlled llama.cpp RPC M1 spike harness landed through `3db6ef9`
- bounded TCP measurement relay landed through `206248a`
- deterministic M1 two-node feasibility planner: current PR #5 changeset; final branch state validated cross-platform before merge

## What exists

### Lab and measurements

- synchronized Windows/Linux lab setup;
- machine-readable node inventory;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- stable random non-hostname lab node IDs;
- versioned local profile revisions and ignored `artifacts/lab/` evidence paths;
- user-facing `tests` action runs benchmark, orchestrator, protocol, identity, scheduler, llama-runtime, network-runtime, and setup suites.

### Durable control/orchestration foundation

- Draft 2020-12 schemas for core state/control records;
- deterministic Job/Reservation state machines;
- transactional SQLite reference persistence;
- durable idempotency, optimistic revisions, lease expiry, restart recovery and request fingerprints;
- atomic reservation → job/stage binding;
- strict common `ControlEnvelope` parsing and structured errors;
- durable handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`.

### Node session and initial wire binding

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

Properties include mandatory injected authentication, protocol-version negotiation, authenticated actor binding, optimistic session revisions, exact replay/semantic request-ID conflict detection, capability intersection, profile/revision binding, benchmark readiness policy, and external termination for revocation/incident signals.

### M1 reference node identity

ADR 0005 is accepted for the **narrow M1 reference implementation**, not as production identity readiness.

Authentication method: `computemesh-ed25519-v1`.

The Ed25519 challenge proof binds session ID, per-session challenge, stable node ID, key ID, negotiated protocol version, proof issue/expiry time, and canonical accepted `NodeHello` semantics.

`services/identity/` provides a SQLite reference registry with stable random node IDs, one-time hashed enrollment tokens, public Ed25519 keys only, idempotent same-token/same-key enrollment, conflict rejection, key rotation, monotonic key/node revocation, and restart persistence.

Revoked keys/nodes are rejected on new authentication. Existing sessions still require external revocation fan-out to the session termination path.

### Controlled llama.cpp M1 runtime experiment

`runtime/llama/rpc_spike.py` is the first executable shared-runtime research harness. It does not make upstream llama.cpp RPC the ComputeMesh node protocol.

Guardrails include literal loopback/RFC1918 RPC endpoints only, coordinator HTTP on `127.0.0.1`, `--offline`, explicit discovered devices, explicit `layer` split/tensor ratios, `--fit off`, disabled prompt/RPC cache surfaces for the first experiment, deterministic request settings, and no advanced tensor overrides in the baseline experiment.

Commands:

- `worker` — start caller-supplied private RPC worker;
- `discover` — obtain exact current llama.cpp local/RPC device names;
- `baseline` — deterministic local-only reference;
- `run` — explicit local + RPC placement;
- `compare` — require same model/prompt digests and compare token-ID digest when available, otherwise output digest.

Evidence records include model SHA-256/size, bounded llama.cpp version, topology/placement, model-ready/request timing, prefill/decode metrics and content digests without raw prompt/output persistence.

**Evidence boundary:** no actual successful shared local+RPC two-machine inference artifact has yet been recorded. ADR 0002 remains Proposed.

### M1 TCP measurement relay

`runtime/network/tcp_relay.py` is a lab measurement instrument, not the production ComputeMesh transport/security boundary.

It listens only on `127.0.0.1`, targets only literal loopback/RFC1918 IPv4, rejects DNS/public/IPv6/wildcard/link-local endpoints, uses bounded queues/backpressure, counts directional opaque TCP bytes, separates setup/active/total timing, supports deterministic userspace stream-chunk delay/jitter and deliberate disconnects, and persists content-free connection/relay failure evidence.

The relay does not parse llama.cpp RPC framing. Byte totals include RPC control/framing/data and are **not activation-tensor byte counts**. Delay/jitter are stream-forwarding effects, not physical packet emulation. Packet loss is deliberately not simulated by dropping TCP bytes; real loss/reordering requires a controlled OS/network layer.

### Deterministic M1 two-node placement planner

`services/scheduler/placement.py` now provides the first machine-readable placement component for the exact two-node llama.cpp experiment. It is a **feasibility planner**, not a production scheduler or performance oracle.

Inputs are existing contract-valid evidence:

- coordinator and worker node profiles;
- model manifest + selected artifact;
- coordinator llama prefill/decode benchmarks;
- worker llama prefill/decode benchmarks;
- coordinator → worker TCP network benchmark;
- explicit worker node ID assertion for that network record;
- explicit model layer count.

Validation/binding behavior:

- validates node-profile, model-manifest, benchmark-result and placement-result schemas;
- coordinator and worker must have different node IDs;
- llama benchmark types and profile revisions must match the exact current node profiles;
- all four llama benchmark records must carry one model basename and an exact `model_size_bytes` equal to the selected model-manifest artifact;
- model manifest must allow `contiguous_layers`;
- profiles older than policy or beyond bounded future clock skew are not usable;
- a draining/stale coordinator blocks both local and shared candidates;
- a draining/stale worker blocks shared placement but does not invalidate an otherwise feasible local coordinator baseline;
- provider `max_memory_fraction` is combined with a conservative planner memory fraction;
- largest reported GPU/accelerator memory is used where present, otherwise currently available system RAM is the CPU fallback.

Conservative shared-memory model:

- explicit layer count is required because `model_manifest` v1 does not yet encode it;
- default 10% model-size fixed coordinator overhead is reserved;
- remaining model bytes are spread uniformly over the explicit layer count for this first feasibility approximation;
- at least one layer must fit on each node;
- emitted layer ranges are contiguous, non-overlapping and cover `[0, layer_count)`;
- layer counts become relative `tensor_split` experiment weights.

This memory model is intentionally an approximation. Real GGUF tensor placement may differ; the actual llama.cpp run remains authoritative.

Recommendation modes:

- `shared_experiment` — memory-feasible candidate for the controlled experiment only;
- `local_only` — shared candidate unavailable, local coordinator baseline feasible;
- `no_plan` — neither candidate currently satisfies hard/memory constraints.

Every decision sets `production_scheduling = false`.

Performance evidence boundary is explicit. The decision records measured node prefill/decode rates and network RTT/throughput, but until a correct measured shared runtime exists it **must** emit:

```text
performance_evidence.status = insufficient_shared_runtime_evidence
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

No formula converts independent node/network measurements into a fabricated shared speedup.

`decision_id` is deterministic over model digest, layer count, node IDs/profile revisions, exact benchmark run IDs and planner policy.

Known contract gaps remain visible:

- `benchmark_result` v1 does not encode the target node ID for a network measurement, so `network_peer_node_id` is a required caller assertion and output labels it `caller_asserted_v1`;
- `model_manifest` v1 does not encode transformer layer count, so layer count is an explicit experiment input.

Result schema: `services/scheduler/placement_decision.schema.json`.

## Latest cross-platform validation

A temporary branch-only GitHub workflow validated the **final current placement branch state** on both supported development platforms. The temporary workflow is removed before merge and is not intended to exist on `main`.

**Windows Server 2025 / Python 3.11.9:**

- scheduler placement: **14/14**;
- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup: **20/20**.

**Ubuntu 24.04 / Python 3.11.16:**

- scheduler placement: **14/14**;
- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup: **20/20**.

Final branch-state workflow run `32530904884` completed successfully on both OS jobs.

Scheduler negative/semantic coverage includes deterministic IDs, contiguous complete ranges, explicit no-speedup prediction, worker-drain local fallback, stale-coordinator no-plan behavior, small-worker fallback, no-memory plan, profile revision mismatch, model-size mismatch, network-peer mismatch, partition permission, CPU-memory fallback, output schema validation and bounded policy values.

The scheduler tests use synthetic contract-valid evidence. They do **not** constitute real target placement/performance evidence.

## Real target-machine evidence from 2026-08-21

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H-class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU detected.
- Windows and Linux direct setup/profile and earlier test flows passed on the real targets.
- Windows → internet Linux engineering TCP benchmark with temporary source-limited firewall rule: RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s; rule removed afterwards.
- Windows CUDA llama.cpp with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`: prefill 2866.127 tokens/s for 512 prompt tokens; decode 76.210 tokens/s for 128 generated tokens.
- Linux CPU llama.cpp smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tokens/s for 128 prompt tokens; decode 0.201 tokens/s for 32 generated tokens.

The public-internet TCP measurement is not a trusted private-LAN A↔B result and is not distributed shared inference. No real placement decision has yet been claimed from the synthetic scheduler tests.

## What does not exist / remains a security or M1 blocker

- trusted private-LAN A↔B assisted benchmark evidence;
- a placement decision generated from a fresh complete real two-node evidence bundle;
- an actual successful two-device local+RPC shared-inference artifact;
- real llama.cpp-through-relay byte/timing results on the target machines;
- activation-tensor-specific transfer accounting;
- real-runtime delay/jitter/disconnect sensitivity evidence;
- packet-level loss/reordering evidence;
- calibrated shared-runtime latency/speedup prediction or production scheduler ranking;
- production provider-node application/service/installer;
- Gateway/API;
- production orchestrator network service/database adapter;
- authenticated/authorized provider-facing identity APIs;
- OS-protected private-key storage in the node agent;
- active-session revocation fan-out;
- authenticated/encrypted ComputeMesh control/data transport;
- general authorization policy, rate/resource limits and abuse controls;
- hardware attestation or Sybil-proof physical-node identity;
- minimum artifact/runtime/result/failure/heartbeat wire operations required by the selected M1 path;
- production registry/verification/billing/telemetry/SDK/UI;
- signed production release/update system.

The current ComputeMesh identity/session layer does **not** authenticate the upstream llama.cpp RPC socket. The relay and planner do not change this. Upstream RPC remains trusted-private-lab-only and must not be treated as the provider-node API. `confidential_compute` remains invalid without a concrete TEE/attestation design.

## ADR status

Accepted:

- ADR 0001 — repository bootstrap;
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**.

Still proposed:

- ADR 0002 — M1 runtime baseline; controlled llama.cpp RPC harness, relay and conservative placement planner exist, but no real correct shared proof yet;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

## Next actions in order

1. On two machines sharing a trusted private LAN, retain fresh A→B and B→A network evidence and fresh node profiles.
2. Use the same GGUF/model manifest and llama-bench evidence on both nodes; generate the first real `services.scheduler.placement` decision and retain its explicit evidence gaps/constraints.
3. Use compatible current llama.cpp builds; run `runtime.llama.rpc_spike discover` and retain exact local/RPC device names.
4. Run deterministic local `baseline` on the coordinator.
5. Start a fresh local measurement relay and execute the planner-selected explicit local+RPC layer split through it.
6. Run `compare`; require same model/prompt digests and exact token/output correctness before making a shared-inference claim.
7. Retain relay directional byte totals plus setup/active timing for that exact successful run.
8. Repeat controlled runs with added stream delay/jitter and deliberate disconnects; retain correctness/performance/failure evidence. If packet loss/reordering is material, test it separately through controlled OS/network emulation.
9. Accept, reject, or supersede ADR 0002 from measured evidence, then calibrate scheduler prediction/ranking from the correct shared result rather than invented coefficients.
10. Bind only the minimum artifact/runtime/result/failure messages required by the winning path and continue toward a reproducible correct two-node inference under ComputeMesh control.

Before any public authenticated node service is introduced, separately complete node private-key storage, provider-authenticated identity APIs, active-session revocation fan-out, transport security, authorization and resource limits.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
