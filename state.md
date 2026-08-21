# ComputeMesh State

**Last updated:** 2026-08-22  
**Phase:** M0 foundation with M1 reference identity, controlled llama.cpp runtime/relay tooling, deterministic two-node feasibility planning, and stronger experiment evidence binding; real shared inference is not yet evidenced  
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
- deterministic M1 two-node feasibility planner landed through `6177218`
- M1 network-peer/model-layer evidence binding introduced through PR #6; cross-platform software validation is required before merge

## What exists

### Lab and measurements

- synchronized Windows/Linux Lab Setup;
- stable random non-hostname Lab node IDs;
- machine-readable node inventory and versioned local profile revisions;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- ignored local evidence under `artifacts/lab/`;
- user-facing `tests` action runs benchmark, orchestrator, protocol, identity, scheduler, llama-runtime, network-runtime, and setup suites.

### Network benchmark evidence binding

The TCP benchmark remains a controlled trusted-private-LAN engineering tool with **no application authentication or encryption**.

Current servers may receive their existing Lab Setup node ID via `--node-id`. On the same benchmark connection a current client can issue the bounded identity query and receive that self-reported Lab ID before measurement.

New network benchmark records can therefore contain:

- `conditions.local_node_id` — the client Lab Setup ID;
- `conditions.peer_node_id` — the server's self-reported Lab Setup ID;
- `conditions.peer_identity_binding = unauthenticated_server_report_v1`.

Properties/limits:

- IDs are bounded to 1..128 printable characters and at most 512 UTF-8 bytes in the benchmark implementation;
- `peer_node_id` and `peer_identity_binding` are schema-paired;
- `--expected-peer-node-id` can make the client fail closed when the current server reports a different ID or no ID;
- legacy benchmark servers remain usable if an expected peer is not required;
- malformed identity queries with a nonzero declared payload are rejected and the connection is closed so unread bytes cannot be reinterpreted as a following benchmark frame;
- Lab Setup automatically passes its own random Lab ID into both server and client benchmark roles.

**Evidence boundary:** `unauthenticated_server_report_v1` is traceability/bookkeeping only. The server can self-report any Lab ID because this benchmark socket is unauthenticated. This is not the ADR-0005 Ed25519/session identity proof and must not be used as a production trust decision.

### Model manifest evidence binding

`model_manifest.schema.json` now accepts optional:

```json
"layer_count": 32
```

The field remains optional so older manifests remain schema-compatible. The M1 planner prefers a manifest `layer_count` and records `layer_count_source = model_manifest_v1`. If a caller also supplies a layer count it must match exactly.

For a legacy manifest without `layer_count`, an explicit caller layer count remains supported and is recorded as `caller_asserted_v1`. If neither source exists the planner rejects the input rather than guessing.

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

Properties include mandatory injected authentication, protocol-version negotiation, authenticated actor binding, optimistic session revisions, exact replay/semantic request-ID conflict detection, capability intersection, profile/revision binding, benchmark readiness policy, and external termination for revocation/incident signals.

ADR 0005 is accepted for the **narrow M1 reference implementation**, not as production identity readiness. Authentication method: `computemesh-ed25519-v1`.

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

`services/scheduler/placement.py` is an experiment **feasibility planner**, not a production scheduler or performance oracle.

Inputs are contract-valid coordinator/worker profiles, model manifest/artifact, four llama-bench records, and coordinator→worker TCP path evidence.

Evidence resolution now prefers embedded facts:

- if `model_manifest.layer_count` exists, it is authoritative for the decision and recorded as `model_manifest_v1`;
- if network conditions contain `local_node_id`, it must equal the coordinator profile node ID;
- if network conditions contain `peer_node_id`, it must equal the worker profile node ID and its `peer_identity_binding` is propagated into the decision;
- an additionally supplied caller peer/layer value may not conflict with embedded evidence;
- older network records/manifests remain usable only through explicit `caller_asserted_v1` fallbacks;
- missing required legacy fallback evidence is rejected rather than inferred.

Other validation/binding behavior:

- llama benchmark types/profile revisions must match the exact current node profiles;
- all four llama benchmark records must carry one model basename and exact model size equal to the selected manifest artifact;
- manifest must allow `contiguous_layers`;
- stale/future-skewed profiles are rejected for candidates that need them;
- a draining/stale coordinator blocks both local and shared candidates;
- a draining/stale worker blocks shared placement but not an otherwise feasible local coordinator baseline;
- provider `max_memory_fraction` combines with a conservative planner memory fraction;
- largest reported GPU/accelerator memory is selected where present, otherwise currently available system RAM is the CPU fallback.

Conservative shared-memory model:

- default 10% model-size fixed coordinator overhead;
- remaining bytes spread uniformly over the resolved layer count;
- at least one layer must fit on each node;
- emitted ranges are contiguous/non-overlapping and cover `[0, layer_count)`;
- layer counts become relative `tensor_split` experiment weights.

This is a planning approximation; real GGUF tensor placement may differ and the actual llama.cpp run remains authoritative.

Recommendation modes:

- `shared_experiment` — memory-feasible candidate for the controlled experiment only;
- `local_only` — shared unavailable, local coordinator baseline feasible;
- `no_plan` — neither candidate currently satisfies hard/memory constraints.

Every decision sets `production_scheduling = false`.

Until a correct measured shared runtime exists, the planner must emit:

```text
performance_evidence.status = insufficient_shared_runtime_evidence
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

No formula converts independent node/network measurements into a fabricated shared speedup.

`decision_id` includes model digest, resolved layer count and source, node IDs/profile revisions, exact benchmark run IDs, network-peer binding source and planner policy.

Result schema: `services/scheduler/placement_decision.schema.json`.

## Latest cross-platform validation

The evidence-binding branch uses a temporary branch-only Windows/Ubuntu workflow before merge. The workflow is removed before `main` is advanced.

Current expected suite counts on each OS after the identity-query framing regression was added:

- benchmark: **18/18**;
- orchestrator: **34/34**;
- protocol: **66/66**;
- identity/integration: **13/13**;
- scheduler placement: **21/21**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup: **21/21**.

Evidence-binding coverage includes legacy/current benchmark interoperability, bounded server-reported Lab IDs, malformed identity-query framing rejection, expected-peer mismatch failure, paired benchmark identity fields, optional manifest layer count, embedded-vs-caller conflict rejection, coordinator/worker network-ID binding, deterministic placement identity and the explicit no-speedup-prediction boundary.

This is software/loopback/synthetic-evidence validation on both OS families. It is **not** real two-machine shared-runtime or placement-performance evidence.

## Real target-machine evidence from 2026-08-21

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H-class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU detected.
- Windows and Linux direct setup/profile and earlier test flows passed on the real targets.
- Windows → internet Linux engineering TCP benchmark with temporary source-limited firewall rule: RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s; rule removed afterwards.
- Windows CUDA llama.cpp with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`: prefill 2866.127 tokens/s for 512 prompt tokens; decode 76.210 tokens/s for 128 generated tokens.
- Linux CPU llama.cpp smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tokens/s for 128 prompt tokens; decode 0.201 tokens/s for 32 generated tokens.

The public-internet TCP measurement predates the new peer-ID binding path, is not a trusted private-LAN A↔B result, and is not distributed shared inference. No real placement decision has yet been claimed from synthetic scheduler tests.

## What does not exist / remains a security or M1 blocker

- fresh trusted-private-LAN A↔B benchmark evidence using the current embedded Lab-ID metadata;
- a placement decision generated from a fresh complete real two-node evidence bundle;
- an actual successful two-device local+RPC shared-inference artifact;
- real llama.cpp-through-relay byte/timing results on the target machines;
- authenticated identity on the benchmark or upstream llama.cpp RPC socket;
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

The current ComputeMesh identity/session layer does **not** authenticate the TCP benchmark or upstream llama.cpp RPC socket. The benchmark Lab-ID self-report, relay and planner do not change this. Upstream RPC and the benchmark remain trusted-private-lab-only. `confidential_compute` remains invalid without a concrete TEE/attestation design.

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

1. On two machines sharing a trusted private LAN, capture fresh node profiles and A→B/B→A network measurements with the current embedded local/peer Lab-ID metadata.
2. Use the same GGUF and a model manifest carrying the correct `layer_count`; retain matching llama-bench evidence on both nodes.
3. Generate the first real `services.scheduler.placement` decision without legacy caller peer/layer fallbacks and retain its hard constraints/candidate.
4. Use compatible current llama.cpp builds; run `runtime.llama.rpc_spike discover` and retain exact local/RPC device names.
5. Run deterministic local `baseline` on the coordinator.
6. Start a fresh local measurement relay and execute the planner-selected explicit local+RPC layer split through it.
7. Run `compare`; require same model/prompt digests and exact token/output correctness before making a shared-inference claim.
8. Retain relay directional byte totals plus setup/active timing for that exact successful run.
9. Repeat controlled runs with added stream delay/jitter and deliberate disconnects. If packet loss/reordering is material, test it separately through controlled OS/network emulation.
10. Accept, reject, or supersede ADR 0002 from measured evidence, then calibrate scheduler prediction/ranking from the correct shared result rather than invented coefficients.
11. Bind only the minimum artifact/runtime/result/failure messages required by the winning path and continue toward reproducible correct two-node inference under ComputeMesh control.

Before any public authenticated node service is introduced, separately complete node private-key storage, provider-authenticated identity APIs, active-session revocation fan-out, transport security, authorization and resource limits.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
