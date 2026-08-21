# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 foundation with M1 reference identity, a controlled llama.cpp runtime harness, and a cross-platform-validated TCP measurement/fault relay; real shared inference is not yet evidenced  
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
- bounded TCP measurement relay: current PR #4 changeset; validated cross-platform before merge

## What exists

### Lab and measurements

- synchronized Windows/Linux lab setup;
- machine-readable node inventory;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- stable random non-hostname lab node IDs;
- versioned local profile revisions and ignored `artifacts/lab/` evidence paths;
- user-facing `tests` action runs benchmark, orchestrator, protocol, identity, llama-runtime, network-runtime, and setup suites.

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

`services/identity/` provides a SQLite reference registry with:

- stable random node IDs independent of key rotation;
- one-time provider-authorized enrollment tokens capped at 15 minutes and stored only as SHA-256;
- Ed25519 public keys only — no node private keys in the control plane;
- idempotent same-token/same-key enrollment;
- conflict rejection for changed-key token replay and duplicate keys across nodes;
- rotation preserving node ID;
- monotonic key/node revocation;
- restart persistence.

Revoked keys/nodes are rejected on new authentication. Existing sessions still require external revocation fan-out to the session termination path.

### Controlled llama.cpp M1 runtime experiment

`runtime/llama/rpc_spike.py` is the first executable shared-runtime research harness. It does not make upstream llama.cpp RPC the ComputeMesh node protocol.

Guardrails:

- upstream RPC endpoint limited to literal loopback/RFC1918 IPv4;
- no DNS/public/IPv6/wildcard assisted endpoint;
- coordinator HTTP bound to `127.0.0.1`;
- `--offline` runtime mode;
- explicit discovered local + RPC device names;
- explicit `layer` split and tensor ratios;
- `--fit off`;
- prompt/RPC cache surfaces disabled for the first experiment;
- deterministic request settings and one server slot;
- no advanced tensor overrides in the baseline experiment.

Commands:

- `worker` — start caller-supplied private RPC worker;
- `discover` — obtain exact current llama.cpp local/RPC device names;
- `baseline` — deterministic local-only reference;
- `run` — explicit local + RPC placement;
- `compare` — require same model/prompt digests and compare token-ID digest when available, otherwise output digest.

Evidence records include model SHA-256/size, bounded llama.cpp version, topology/placement, model-ready/request timing, prefill/decode metrics and content digests without raw prompt/output persistence.

**Evidence boundary:** no actual successful shared local+RPC two-machine inference artifact has yet been recorded. ADR 0002 remains Proposed.

### M1 TCP measurement relay

`runtime/network/tcp_relay.py` is a lab measurement instrument for the current llama.cpp RPC experiment. It is **not** the production ComputeMesh transport or security boundary.

Behavior:

- listener is hard-coded to `127.0.0.1`;
- target must be literal loopback/RFC1918 IPv4;
- DNS, public IPv4, wildcard, link-local and IPv6 targets are rejected;
- full-duplex forwarding uses bounded userspace queues/backpressure;
- counts successfully forwarded opaque TCP-stream bytes independently as coordinator → worker and worker → coordinator;
- separates `setup_elapsed_ms`, `active_elapsed_ms`, and `total_elapsed_ms`;
- supports deterministic userspace one-way stream-chunk delay and bounded jitter;
- supports deliberate disconnect after active connected time or total successfully forwarded bytes;
- persists content-free `connect_error` / `relay_error` evidence with bounded exception type / errno metadata;
- records no payload, prompt, model output or arbitrary stream content.

The relay does not parse llama.cpp RPC framing. Its byte totals therefore contain RPC control/framing/data traffic and are **not activation-tensor byte counts**.

Delay/jitter are TCP-stream-chunk forwarding effects, not physical packet-level network emulation. The relay deliberately does not emulate packet loss by dropping TCP bytes because that would corrupt the reliable byte stream rather than model IP loss/retransmission. Packet-level loss/reordering requires a controlled OS/network layer such as `tc netem` or an equivalent testbed.

Result schema: `runtime/network/relay_metrics.schema.json`.

## Latest cross-platform validation

A temporary branch-only GitHub workflow validated the code changes on both supported development platforms. The temporary workflow is removed before merge and is not intended to exist on `main`.

**Windows Server 2025 / Python 3.11.9:**

- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup: **20/20**.

**Ubuntu 24.04 / Python 3.11.16:**

- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- llama runtime spike: **12/12**;
- network runtime relay: **10/10**;
- setup: **20/20**.

Network relay coverage includes public/DNS/IPv6/wildcard/link-local rejection, bounded configuration, real loopback full-duplex forwarding with exact byte accounting, delayed forwarding, setup-vs-active timing, byte-triggered disconnect, active-time-triggered disconnect, worker-connect failure evidence, and content-free schema validation.

This is local software/loopback evidence on both OS families. It is not real two-machine RPC relay performance evidence.

## Real target-machine evidence from 2026-08-21

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H-class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU detected.
- Windows and Linux direct setup/profile and earlier test flows passed on the real targets.
- Windows → internet Linux engineering TCP benchmark with temporary source-limited firewall rule: RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s; rule removed afterwards.
- Windows CUDA llama.cpp with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`: prefill 2866.127 tokens/s for 512 prompt tokens; decode 76.210 tokens/s for 128 generated tokens.
- Linux CPU llama.cpp smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tokens/s for 128 prompt tokens; decode 0.201 tokens/s for 32 generated tokens.

The public-internet TCP measurement is not a trusted private-LAN A↔B result and is not distributed shared inference.

## What does not exist / remains a security or M1 blocker

- trusted private-LAN A↔B assisted benchmark evidence;
- an actual successful two-device local+RPC shared-inference artifact;
- real llama.cpp-through-relay byte/timing results on the target machines;
- activation-tensor-specific transfer accounting;
- real-runtime delay/jitter/disconnect sensitivity evidence;
- packet-level loss/reordering evidence;
- production provider-node application/service/installer;
- automatic scheduler/placement selection;
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

The current ComputeMesh identity/session layer does **not** authenticate the upstream llama.cpp RPC socket. The local relay does not change this. Upstream RPC remains trusted-private-lab-only and must not be treated as the provider-node API. `confidential_compute` remains invalid without a concrete TEE/attestation design.

## ADR status

Accepted:

- ADR 0001 — repository bootstrap;
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**.

Still proposed:

- ADR 0002 — M1 runtime baseline; controlled llama.cpp RPC harness + measurement relay exist, but no real shared proof yet;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

## Next actions in order

1. On two machines sharing a trusted private LAN, retain A→B and B→A network evidence.
2. Use compatible current llama.cpp builds and the same GGUF; run `runtime.llama.rpc_spike discover` and retain exact local/RPC device names.
3. Run deterministic local `baseline` on the coordinator.
4. Start a fresh local measurement relay and run an explicit local+RPC layer split through it with fixed tensor ratios.
5. Run `compare`; require same model/prompt digests and exact token/output correctness before making a shared-inference claim.
6. Retain relay directional byte totals plus setup/active timing for that exact successful run.
7. Repeat controlled runs with added stream delay/jitter and deliberate disconnects; retain correctness/performance/failure evidence.
8. If packet loss/reordering sensitivity is material, test it separately through a controlled OS/network-emulation layer rather than dropping TCP bytes in the relay.
9. Accept, reject, or supersede ADR 0002 from measured evidence.
10. Bind only the minimum artifact/runtime/failure messages and first machine-readable placement decision required by the winning path; then produce a reproducible correct two-node inference and begin scheduler calibration.

Before any public authenticated node service is introduced, separately complete node private-key storage, provider-authenticated identity APIs, active-session revocation fan-out, transport security, authorization and resource limits.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
