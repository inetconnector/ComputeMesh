# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 foundation with M1 reference identity plus a cross-platform-validated controlled llama.cpp M1 runtime experiment harness; real shared inference is not yet evidenced  
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
- M1 reference node identity landed on `main` through `d45406f`
- controlled llama.cpp RPC M1 spike harness: current changeset; ADR 0002 remains Proposed pending real two-node evidence

## What exists

### Lab and measurements

- synchronized Windows/Linux lab setup;
- machine-readable node inventory;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- stable random non-hostname lab node IDs;
- versioned local profile revisions and ignored `artifacts/lab/` evidence paths;
- the user-facing `tests` action now executes benchmark, orchestrator, protocol, identity, llama-runtime, and setup suites.

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

Properties:

- no permissive/default authenticator;
- explicit protocol major/minor negotiation;
- verifier-confirmed node identity bound to `actor_id`;
- optimistic session revisions;
- exact session-local request replay and semantic request-ID conflict detection;
- capability intersection and mandatory configured capabilities;
- profile node/revision binding;
- benchmark profile revision binding;
- injected benchmark-readiness policy with no accept-all default;
- external termination path for revocation/incident signals.

### M1 reference node identity

ADR 0005 is accepted for the **narrow M1 reference implementation**, not as a claim of public-alpha readiness.

Authentication method: `computemesh-ed25519-v1`.

The Ed25519 challenge signature is domain-separated and binds session ID, per-session challenge, stable node ID, key ID, negotiated protocol version, proof issue/expiry time, and a canonical digest of accepted `NodeHello` semantics including capabilities and supported auth methods.

Reference identity registry (`services/identity/`) provides:

- random stable `node_id` independent of key rotation;
- one-time provider-authorized enrollment tokens capped at 15 minutes and stored only as SHA-256 hashes;
- Ed25519 public keys only — no node private keys in the control-plane reference store;
- idempotent same-token/same-key enrollment;
- changed-key replay and duplicate-key-across-nodes rejection;
- rotation preserving node ID;
- monotonic key/node revocation and no revoked-key reactivation;
- restart-persistent SQLite state.

A revoked key or node is unavailable to **new authentication attempts**. Existing authenticated sessions still require external revocation fan-out to the session termination path.

### Controlled llama.cpp M1 runtime experiment

`runtime/llama/rpc_spike.py` now provides the first executable shared-runtime experiment controller. It is a **research harness**, not a production worker and not a ComputeMesh network protocol.

Experiment guardrails:

- upstream RPC worker endpoint must be a literal loopback or RFC1918 IPv4 address;
- DNS names, public IPs, IPv6 and wildcard binds are rejected by the assisted path;
- coordinator llama-server HTTP binds only to `127.0.0.1`;
- runtime-side acquisition is disabled with `--offline`;
- shared mode requires explicit local + RPC device names discovered from the actual llama.cpp build;
- shared placement uses explicit `--split-mode layer` and `--tensor-split`;
- `--fit off` prevents automatic placement from silently rewriting the experiment;
- prompt cache is disabled (`--cache-ram 0`, request `cache_prompt=false`);
- upstream RPC file cache is not enabled;
- one parallel server slot and deterministic greedy request settings are used for the first correctness comparison;
- advanced tensor overrides are deliberately absent from the baseline experiment.

Commands:

- `worker` — start a caller-supplied upstream RPC worker binary with private-bind checks;
- `discover` — attach private RPC endpoint(s) and print current llama.cpp device names;
- `baseline` — run deterministic local-only llama-server reference execution;
- `run` — run explicit local + RPC shared placement;
- `compare` — require same model/prompt digests and compare token-ID digest when available, otherwise output digest.

Evidence output:

- full model SHA-256 and size;
- bounded `llama-server --version` output;
- private RPC topology and local coordinator endpoint;
- explicit device names, split mode and tensor ratios;
- model-ready time and end-to-end request time;
- upstream prefill/decode timing metrics;
- SHA-256 digests of prompt, output and returned token IDs when available;
- no persisted raw prompt or output content;
- bounded structured failure artifact with phase/type/diagnostic when a measured run fails after output creation.

Result schema: `runtime/llama/spike_result.schema.json`.

**Evidence boundary:** no actual shared local+RPC run has yet been recorded. The harness does not prove that llama.cpp RPC satisfies M1.

## Latest cross-platform validation

A temporary branch-only GitHub workflow validated the actual runtime-harness code on Windows and Ubuntu. The workflow file is removed before merge and is not intended to exist on `main`.

**Windows Server 2025 / Python 3.11.9:**

- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- llama runtime spike: **12/12**;
- setup: **20/20**.

**Ubuntu 24.04 / Python 3.11.16:**

- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- llama runtime spike: **12/12**;
- setup: **20/20**.

The runtime tests cover private endpoint restrictions, no-cache worker construction, offline discovery, explicit local+RPC placement invariants, loopback-only coordinator HTTP, deterministic/no-prompt-cache request shape, bounded response parsing, model hashing, failure-record privacy, baseline/shared comparison, and a schema that forbids raw prompt/output fields.

## Real target-machine evidence from 2026-08-21

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H-class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU detected.
- Windows direct setup/profile and earlier full test flow passed on the real target.
- Linux direct setup/profile and earlier full test flow passed on the real target.
- Windows → internet Linux TCP engineering benchmark with temporary source-limited firewall rule: RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s; rule removed afterwards.
- Windows CUDA llama.cpp with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`: prefill 2866.127 tokens/s for 512 prompt tokens; decode 76.210 tokens/s for 128 generated tokens.
- Linux CPU llama.cpp smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tokens/s for 128 prompt tokens; decode 0.201 tokens/s for 32 generated tokens.

The public-internet TCP measurement is not a trusted private-LAN A↔B result and is not distributed shared inference.

## What does not exist / remains a security or M1 blocker

- trusted private-LAN A↔B assisted benchmark evidence;
- an actual successful two-device local+RPC shared-inference artifact;
- activation/RPC transfer byte accounting;
- controlled latency/jitter/loss experiments;
- deliberate worker-disconnect/cancellation evidence;
- production provider-node application/service/installer;
- automatic scheduler/placement selection for the runtime split;
- Gateway/API;
- production orchestrator network service/database adapter;
- authenticated/authorized provider-facing identity APIs;
- OS-protected private-key storage in the node agent;
- active-session revocation fan-out;
- authenticated/encrypted ComputeMesh control/data transport;
- general authorization policy, rate/resource limits and abuse controls;
- hardware attestation or Sybil-proof physical-node identity;
- minimum artifact/runtime/result/failure/heartbeat wire operations required by the finally selected M1 path;
- production registry/verification/billing/telemetry/SDK/UI;
- signed production release/update system.

The current ComputeMesh identity/session layer does **not** authenticate the upstream llama.cpp RPC socket. Upstream RPC remains trusted-lab-only and must not be treated as the provider-node API. A copied private key remains cryptographically the same node identity. `confidential_compute` remains invalid without a concrete TEE/attestation design.

## ADR status

Accepted:

- ADR 0001 — repository bootstrap;
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**.

Still proposed:

- ADR 0002 — M1 runtime baseline; controlled llama.cpp RPC experiment harness exists, but no real shared proof yet;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

## Next actions in order

1. On two machines sharing a trusted private LAN, retain A→B and B→A network evidence.
2. Use compatible current llama.cpp builds and the same GGUF; run `runtime.llama.rpc_spike discover` and retain exact local/RPC device names.
3. Run the deterministic `baseline` on the coordinator.
4. Run `run` with an explicit local+RPC layer split and fixed tensor ratios.
5. Run `compare`; require same model/prompt digests and exact token/output correctness before making any shared-inference claim.
6. Record host/device memory behavior and deliberately disconnect the worker during controlled runs; retain structured failure evidence.
7. Add activation/RPC transfer-size accounting and controlled latency/jitter/loss experiments.
8. Accept, reject, or supersede ADR 0002 from the measured evidence.
9. Bind only the minimum artifact/runtime/failure messages and first machine-readable placement decision required by the winning M1 path.
10. Produce a reproducible correct two-node inference and begin scheduler calibration.

Before any public authenticated node service is introduced, separately complete node private-key storage, provider-authenticated identity APIs, active-session revocation fan-out, transport security, authorization and resource limits.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
