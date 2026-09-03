# P0 Confidential Execution Program

**Status:** mandatory architecture and production-release gate  
**Priority:** P0 / non-negotiable  
**Scope:** customer prompt, output, token IDs, intermediate activations, content keys and confidential execution metadata

## Objective

ComputeMesh must support protected inference in which an untrusted provider operator, a network observer and ordinary control-plane services cannot obtain plaintext customer content or reusable content keys. Protected execution must be fail-closed: if the complete required protection chain cannot be verified for a job, that job must not execute as protected and must never silently downgrade to `PUBLIC`.

This document deliberately separates **target security guarantees** from **current implementation state**. A component existing in the repository is not sufficient to claim the complete guarantee until it is wired into the live execution path and validated on real hardware.

## Required protected-execution chain

For `CONFIDENTIAL` and `CRYPTO_PRIVATE` jobs the production architecture must establish, in order:

1. authenticated client/gateway transport;
2. a job-specific content-encryption context;
3. provider/runtime selection that satisfies the requested privacy class;
4. fresh remote attestation bound to node identity, exact measured runtime, nonce, debug-disabled state and an ephemeral public key;
5. content-key release only to that verified attested ephemeral key;
6. authenticated/encrypted data-plane transport whose endpoint identity is bound to the attested execution environment;
7. protected execution memory with page locking where applicable, no swap/core-dump exposure, bounded plaintext lifetime and explicit zeroization;
8. production split/blinding only when mathematically valid for the exact model/runtime transformation;
9. no raw prompt/output in default logs, evidence or telemetry;
10. encrypted/bound result return and destruction of request-scoped secrets;
11. auditable evidence that the requested privacy class was satisfied without revealing content.

Failure at any required step terminates the protected request before content-key release or plaintext execution.

## Privacy classes

### `PUBLIC`

Ordinary admitted compute. Transport encryption and node authentication are required, but the provider runtime may technically observe workload data. `PUBLIC` must never be described as confidential execution.

### `CONFIDENTIAL`

Requires real hardware-backed confidential execution and fresh attestation. The production target is a measured CPU/GPU trusted-execution boundary with encrypted memory and an attested key-release path. TLS, VM/container isolation, code signing, ordinary sharding or blinding alone do not satisfy this class.

### `CRYPTO_PRIVATE`

Requires a validated cryptographic private-computation mechanism whose confidentiality does not depend solely on trusting a provider host. Candidate mechanisms include MPC/secret sharing and, where practical, FHE or hybrid protocols. An unvalidated orthogonal transform or ordinary activation sharding does not satisfy this class.

## P0 workstreams

### P0-A — hard fail-closed runtime gate

- one central protected-execution readiness contract;
- protected jobs require every configured mandatory capability;
- explicit reason codes for missing attestation, key release, protected memory, encrypted data plane, validated split/blinding and logging policy;
- no fallback to `PUBLIC` or raw llama.cpp RPC.

### P0-B — secure memory

- AES-256-GCM required; no insecure cryptographic fallback;
- mutable plaintext buffers only;
- `mlock`/`VirtualLock` for request-scoped plaintext buffers when required by policy;
- fail closed when mandatory memory locking cannot be established;
- no unnecessary immutable Python `bytes` copies of protected plaintext;
- zeroize plaintext, nonce and request-scoped keys after use;
- disable core dumps for protected worker processes where supported;
- production TEE memory encryption remains the protection against a hostile host administrator; `mlock` is defense in depth against paging, not a TEE replacement.

### P0-C — remote attestation and key release

- concrete technology verifiers, not generic/simulated labels;
- bind attestation to node ID, runtime digest/measurement, nonce, validity window, debug-disabled state and ephemeral public key;
- release content keys only to the verified attested ephemeral key;
- gateway/control plane must not hold a universal content-decryption key;
- replay, stale attestation and key-substitution tests.

### P0-D — production data plane

- protected jobs must not use unauthenticated/raw upstream llama.cpp RPC over an untrusted path;
- endpoint/channel binding to the attested runtime;
- authenticated encryption in transit, replay protection and bounded framing;
- private-network/SSH tunnelling remains a development containment mechanism, not the final confidential data plane.

### P0-E — mathematically valid blinded/split inference

- `services/gateway/blind_inference.py` is currently a prototype building block, not proof that the live model is privacy-preserving;
- define the exact transformation for each supported model architecture and prove that transformed execution is functionally equivalent within an explicit tolerance/correctness criterion;
- do not claim that a simple hidden-state rotation can be inserted around arbitrary unchanged transformer layers;
- hidden-state leakage must be evaluated adversarially;
- use blinding as defense in depth with TEE unless a separate cryptographic construction provides an independently reviewed confidentiality guarantee.

### P0-F — concrete TEE backends

- technology-specific verifier plugins;
- measured runtime allowlist/digest policy;
- real hardware acceptance tests;
- CPU-TEE/GPU-TEE composition where the workload crosses both boundaries;
- device/driver/runtime version binding;
- debug mode and attestation freshness enforcement;
- revocation/update strategy.

### P0-G — adversarial acceptance

Protected production release is blocked until tests cover at least:

- network MITM/replay;
- fake/stale/wrong-node attestation;
- attestation with debug enabled;
- runtime measurement mismatch;
- ephemeral-key substitution;
- content-key replay/cross-job reuse;
- provider root/admin memory-inspection threat against the declared TEE boundary;
- swap/pagefile/core-dump checks;
- plaintext-log/telemetry scan;
- malformed encrypted envelopes;
- data-plane downgrade attempts;
- split/blinding correctness and privacy-leakage tests;
- provider disconnect/restart during protected jobs.

## Current repository state at start of this program

Already present as foundations:

- fail-closed privacy classes and routing policy;
- technology-agnostic confidential-attestation envelope verification;
- attestation-bound key-release contract;
- AES-GCM/zeroization/page-locking primitives;
- an early blinded split-inference prototype;
- authenticated provider-control sessions and Ed25519 identities;
- explicit documentation that ordinary llama.cpp RPC is not a public security boundary.

Not yet sufficient for the complete guarantee:

- the live inference path does not yet require the complete P0 chain;
- no concrete production TEE verifier is enabled by default;
- raw/experimental llama.cpp RPC remains part of the development shared-runtime path;
- the current blinding prototype is not integrated as a mathematically validated transformed model runtime;
- secure-memory primitives require additional fail-closed integration and copy-elimination hardening;
- physical adversarial confidential-compute acceptance is still outstanding.

## Definition of done

A protected job is considered production-ready only when the system can produce content-free evidence that all mandatory protections for the requested privacy class were active, and negative testing demonstrates that removing or falsifying any mandatory protection causes the request to fail before protected plaintext is exposed.

The website and README may describe this as the mandatory ComputeMesh security architecture, but must distinguish that architecture from the currently validated production state until this definition of done is met.
