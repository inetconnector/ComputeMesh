# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 foundation with node-session wire binding and an accepted M1 reference node-identity mechanism; next gate is the narrow M1 runtime proof  
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
- M1 reference node identity: `computemesh-ed25519-v1`, with SQLite enrollment/key registry and cross-platform validation in the current identity changeset

## What exists

### Lab and measurements

- synchronized Windows/Linux lab setup;
- machine-readable node inventory;
- TCP RTT/throughput benchmark;
- llama.cpp `llama-bench` prefill/decode adapter;
- stable random non-hostname lab node IDs;
- versioned local profile revisions and ignored `artifacts/lab/` evidence paths.

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

The Ed25519 challenge signature is domain-separated and binds:

- session ID;
- per-session challenge;
- stable node ID;
- key ID;
- negotiated protocol version;
- proof issue/expiry time;
- canonical digest of accepted `NodeHello` semantics, including capabilities and supported auth methods.

Reference proof policy:

- default proof TTL 30 seconds;
- maximum proof TTL 60 seconds;
- bounded clock skew;
- malformed, oversized and extreme-timestamp proofs are denied without escaping the verifier boundary;
- deterministic key fingerprint checked before signature verification;
- successful proof yields a bounded authenticated session lifetime.

Reference identity registry (`services/identity/`):

- SQLite reference implementation only;
- random stable `node_id` independent of key rotation;
- one-time provider-authorized enrollment tokens, at most 15 minutes;
- enrollment tokens stored only as SHA-256 hashes;
- control plane stores Ed25519 **public keys only**;
- same consumed token + same key is idempotent;
- changed-key token replay conflicts;
- same public key cannot enroll as a second node;
- rotation preserves node ID;
- prior active keys may be atomically revoked;
- key/node revocation is monotonic;
- revoked keys cannot be reactivated through rotation;
- registry state survives restart.

A revoked key or node is unavailable to **new authentication attempts**. Existing authenticated sessions still require an external revocation signal/fan-out to the session termination path.

## Cross-platform verification evidence

A temporary branch-only GitHub validation workflow was used for the identity changeset and passed on both supported development platforms. The workflow file is not part of the intended `main` state.

**Windows Server 2025 / Python 3.11.9:**

- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- setup: **20/20**.

**Ubuntu 24.04 / Python 3.11.16:**

- benchmark: **13/13**;
- orchestrator: **34/34**;
- protocol: **64/64**;
- identity/integration: **13/13**;
- setup: **20/20**.

Both runners installed `cryptography 46.0.7` from `requirements-dev.txt` successfully.

Identity negative/integration coverage includes:

- real Ed25519 enrollment → verifier → session-wire authentication;
- session/challenge binding;
- `NodeHello` capability/auth-method tampering;
- expired/future/oversized/extreme-timestamp proofs;
- malformed credentials and signatures;
- unknown/revoked keys;
- token replay/conflict/expiry;
- duplicate public-key enrollment rejection;
- stable node ID across rotation;
- monotonic key/node revocation;
- wrong-principal rotation/revocation rejection;
- timezone requirements;
- SQLite restart persistence.

## Real target-machine evidence from 2026-08-21

- Windows target: `lab-d6332cbe`, Windows 10, Python 3.11.9, Intel i7-11800H-class CPU, 31.7 GiB RAM, NVIDIA GeForce RTX 3080 Laptop GPU, 16 GiB VRAM, driver 595.79.
- Linux target: Debian 13/trixie, Linux 6.12.94, Python 3.13.5, 4 logical cores, 7.8 GiB RAM, no GPU detected.
- Windows direct setup/profile and full earlier test flow passed on the real target.
- Linux direct setup/profile and full earlier test flow passed on the real target.
- Windows → internet Linux TCP engineering benchmark with temporary source-limited firewall rule: RTT p50 11.884 ms, p95 13.369 ms, upload p50 42.276 Mbit/s, download p50 226.597 Mbit/s; rule removed afterwards.
- Windows CUDA llama.cpp with `qwen2.5-coder-7b-instruct-q4_k_m.gguf`: prefill 2866.127 tokens/s for 512 prompt tokens; decode 76.210 tokens/s for 128 generated tokens.
- Linux CPU llama.cpp smoke with `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf`: prefill 12.382 tokens/s for 128 prompt tokens; decode 0.201 tokens/s for 32 generated tokens.

**Evidence boundary:** the Windows↔Linux network measurement used a public-internet Linux server and is not a trusted private-LAN A↔B result. There is still no distributed shared inference result.

## What does not exist / remains a security or M1 blocker

- trusted private-LAN A↔B assisted benchmark evidence;
- production provider-node application/service/installer;
- distributed runtime/shared inference;
- Gateway/API/scheduler;
- production orchestrator network service/database adapter;
- authenticated/authorized identity service APIs deriving provider principal from a real login/service identity;
- OS-protected private-key storage in the node agent;
- active-session revocation fan-out;
- authenticated/encrypted control/data transport;
- general authorization policy, rate/resource limits and abuse controls;
- hardware attestation or Sybil-proof physical-node identity;
- remaining artifact/runtime/result/failure/heartbeat wire operations required by the exact M1 runtime path;
- production registry/verification/billing/telemetry/SDK/UI;
- signed production release/update system.

A copied private key is cryptographically the same node identity. Ed25519 does not prove a unique physical machine or an uncompromised host. `confidential_compute` remains invalid without a concrete TEE/attestation design.

## ADR status

Accepted:

- ADR 0001 — repository bootstrap;
- ADR 0005 — node identity/key lifecycle **for the narrow M1 reference implementation only**.

Still proposed:

- ADR 0002 — M1 runtime baseline;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

ADR 0005 acceptance does not imply production identity readiness or public network exposure approval.

## Next actions in order

1. When two machines share a trusted private LAN, run assisted A→B and B→A measurements and retain the evidence. This no longer blocks hardware-independent software work.
2. Use the measured llama.cpp evidence and current upstream capabilities to decide the narrow ADR-0002 M1 runtime baseline.
3. Implement the first controlled llama.cpp-oriented remote-stage/runtime spike **behind the ComputeMesh boundary**; do not expose upstream experimental RPC as the public node protocol.
4. Measure activation/remote-stage payload size and add controlled latency/jitter/loss experiments.
5. Bind only the minimum remaining artifact/runtime/failure messages required by that exact M1 spike.
6. Produce the first correct two-node shared inference with explicit correctness, timing and failure evidence.
7. Add the first machine-readable placement decision from real profiles and measured topology.
8. Before introducing a real authenticated node network service, implement supported Windows/Linux node-agent private-key storage and authenticated provider-facing enrollment/rotation/revocation APIs.
9. Add active-session revocation fan-out, authorization policy and rate/resource limits.
10. Re-evaluate G0/G1 and widen the runtime/message surface only after the narrow proof is reproducible.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
