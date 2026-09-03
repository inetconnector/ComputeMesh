# P0 Confidential Execution Program

**Status:** mandatory architecture and production-release gate  
**Priority:** P0 / non-negotiable  
**Current as of:** 2026-09-03  
**Scope:** customer prompt, output, token IDs, intermediate activations, content keys and confidential execution metadata

## Objective

ComputeMesh must support protected inference in which an untrusted provider operator, a network observer and ordinary gateway/control-plane services cannot obtain plaintext customer content, reusable content keys or semantically useful protected intermediate state outside the declared protected boundary.

Protected execution must fail closed. If the complete required protection chain cannot be verified for a job, that job must not execute as protected and must never silently downgrade to `PUBLIC`.

This document separates:

- target production guarantees;
- merged public foundations;
- branch-local implementation;
- software/CI validation;
- physical/adversarial acceptance.

No branch-local or CI-only result is a physical TEE guarantee.

## User-facing API invariant

The product-facing API remains OpenAI-compatible:

- `POST /v1/chat/completions`;
- `GET /v1/models`;
- ordinary non-stream Chat Completions objects;
- ordinary OpenAI SSE chunks for streaming.

For protected requests, a trusted local ComputeMesh proxy/transport is part of the client boundary so the original OpenAI-shaped request can be encrypted before remote egress. Internal `/internal/v1/confidential/...` routes are transport internals and are not a second public user API.

## Required protected-execution chain

For `CONFIDENTIAL`, the production architecture must establish, in order:

1. authenticated client/account context;
2. pre-content session admission and financial reservation;
3. provider/runtime selection satisfying the requested privacy and model constraints;
4. fresh request-scoped attestation challenge;
5. authenticated provider-control delivery of that challenge to the selected node;
6. a dedicated protected worker generating/holding request-scoped X25519 recipient material and Ed25519 metering identity inside the declared protected boundary;
7. technology-specific attestation binding node, measured runtime, freshness challenge/nonce, protected endpoint TLS identity, recipient public key and metering public key;
8. independent local-client verification of the vendor evidence and approved runtime policy;
9. authenticated confidential-envelope binding including account, job, node, runtime, attestation, privacy class, operation, model and prompt/completion token budgets;
10. TLS-pinned encrypted data-plane transport;
11. worker-side and gateway-side replay protection;
12. protected memory/process handling with bounded plaintext lifetime, page locking where required, dump hardening and explicit zeroization;
13. approved inference runtime only;
14. encrypted response before data leaves the protected boundary;
15. content-free signed usage receipt;
16. durable `METERED` checkpoint before financial settlement;
17. idempotent double-entry settlement/release/recovery;
18. content-free audit evidence and no raw prompt/output/token-ID/activation logging outside the protected boundary.

Failure at any mandatory step terminates the protected request without downgrade.

## Privacy classes

### `PUBLIC`

Ordinary admitted compute. Provider runtime may technically observe workload data. Transport security is still required, but `PUBLIC` is not confidential execution.

### `CONFIDENTIAL`

Requires the complete hardware-backed protected-execution chain above and a technology-specific verifier for the concrete supported topology.

### `CRYPTO_PRIVATE`

Requires a separately validated cryptographic private-computation construction such as MPC/secret sharing/FHE/hybrid as appropriate. The current orthogonal hidden-state rotation prototype does not satisfy this class.

## Merged public foundations

The following are merged to public `main`:

- [x] PR #72 — central fail-closed protected-execution foundation;
- [x] PR #73 — attestation-bound X25519/HKDF/AES-256-GCM confidential envelope foundation;
- [x] PR #74 — hash-pinned NVIDIA confidential-attestation verifier-process boundary;
- [x] AES-256-GCM secure-memory primitive with explicit zeroization;
- [x] optional mandatory page locking for protected policy;
- [x] POSIX dumpability/core-dump hardening primitive;
- [x] request-scoped attestation and key-release contracts.

## Current branch-local implementation — PR #76

PR #76 (`security/p0-confidential-metering`) is open and draft. It must not be represented as merged or production-ready.

### Protocol and client transport

- [x] authenticated confidential request/response envelopes;
- [x] model ID and prompt/completion token budgets included in the protected binding;
- [x] request/response key separation;
- [x] durable replay tombstones;
- [x] TLS-pinned protected HTTPS data plane;
- [x] authenticated encrypted streaming frames with sequence/final binding;
- [x] loopback-only OpenAI-compatible local protected proxy;
- [x] local decryption/validation back into ordinary OpenAI JSON/SSE;
- [x] old custom public confidential aliases are not the intended user surface.

### Session, metering and accounting

- [x] durable confidential session store;
- [x] `OPEN -> DISPATCHED -> METERED -> COMPLETED` plus failure state;
- [x] pre-content admission/reservation;
- [x] attestation-bound Ed25519 content-free usage receipts;
- [x] receipt binding to account/job/request/response/node/runtime/privacy/operation/model/token counts;
- [x] `METERED` persisted before financial settlement;
- [x] durable double-entry confidential escrow;
- [x] restart/idempotent settlement and release recovery;
- [x] owner-aware marketplace versus self-compute accounting.

### Canonical gateway composition

- [x] protected internal routes implemented as a pure mixin;
- [x] one canonical unified live protected gateway handler composition;
- [x] protected mode remains unavailable when required coordinator/replay/data-plane components are absent;
- [x] internal protected routes authenticate the unified owner/account context.

### Public/private broker boundary

- [x] public `RemoteConfidentialSessionBroker` sends only content-free admission metadata to the private control plane;
- [x] public broker accepts only a reduced provision containing selected endpoint/evidence material;
- [x] private candidate pools, losing candidates, ranking scores, fraud/reputation features and pricing coefficients remain outside the public response contract;
- [x] public provider-control handler provisions through an already authenticated `NodeSession`;
- [x] provider-control handler binds request to session ID/revision and authenticated node identity;
- [x] provider-control handler requires negotiated confidential capability and proves requested model availability before provisioning.

### Protected worker boundary

- [x] dedicated protected worker/session manager exists;
- [x] dedicated HTTPS worker boundary exists;
- [x] request-scoped X25519 recipient material;
- [x] Ed25519 metering identity;
- [x] exact session/envelope binding and replay checks;
- [x] protected-memory/process-hardening hooks;
- [x] encrypted response handling and content-free receipt generation;
- [x] raw public llama.cpp RPC is not treated as the protected public security boundary.

These items are software foundations. Production confidentiality remains blocked on real end-to-end provisioning/deployment and physical vendor-attestation acceptance.

## Remaining P0 work — current order

### A. Private confidential provisioning and end-to-end control path

- [ ] implement/finish the private confidential-provision service endpoint with a dedicated internal service credential;
- [ ] select only a node satisfying requested protected capability/model/policy;
- [ ] deliver a fresh challenge through the already authenticated provider-control session;
- [ ] obtain the protected worker's reduced provision/evidence without exposing private ranking internals;
- [ ] return only the reduced selected provision to the public gateway;
- [ ] prove end-to-end that the local client independently verifies the vendor attestation rather than trusting control-plane `verified=true` state.

### B. Canonical production bootstrap/readiness

- [ ] construct durable confidential session DB, replay DB and confidential escrow in live startup;
- [ ] construct non-stream and stream TLS-pinned protected data planes;
- [ ] install remote broker, coordinator and verifier policy;
- [ ] run metered-session recovery on startup;
- [ ] expose readiness that distinguishes ordinary public inference from confidential readiness;
- [ ] confidential readiness must be false unless the complete required chain is installed;
- [ ] no raw RPC fallback for protected requests.

### C. OpenAI compatibility acceptance

- [ ] official/current OpenAI Python client: non-stream protected completion;
- [ ] official/current OpenAI Python client: `stream=True`;
- [ ] verify supported roles and message shapes;
- [ ] tool calls/tool results and `tool_choice`;
- [ ] `response_format` / supported structured output;
- [ ] sampling/stop/seed fields where runtime supports them;
- [ ] `max_tokens` / `max_completion_tokens` compatibility policy;
- [ ] usage and streaming finish-reason semantics;
- [ ] unsupported semantically important fields must fail explicitly with OpenAI-shaped errors rather than being silently ignored;
- [ ] `/v1/models` must reflect actual live model availability.

### D. Real NVIDIA confidential-compute attestation

- [ ] build the small operator-reviewed helper against the currently supported NVIDIA confidential-compute attestation SDK/stack;
- [ ] hash-pin the helper binary;
- [ ] validate real evidence, nonce/freshness, production CC state, debug-disabled state and required measurements;
- [ ] bind and validate runtime digest, recipient public key, metering public key and TLS endpoint identity;
- [ ] run on supported NVIDIA confidential-compute hardware;
- [ ] record physical acceptance evidence and negative tests.

### E. AMD confidential execution

- [ ] implement only for a concrete topology whose CPU/CVM/device chain can actually prove the requested protection;
- [ ] evaluate SEV-SNP plus device-assignment/TDISP path where applicable;
- [ ] never equate ordinary ROCm/Vulkan execution with confidential computing;
- [ ] perform physical acceptance before enabling/claiming the class.

### F. `CRYPTO_PRIVATE`

- [ ] formally define the threat/leakage model;
- [ ] select a cryptographic construction appropriate to the supported model/runtime;
- [ ] prove functional correctness/equivalence as required;
- [ ] run adversarial leakage evaluation;
- [ ] never set a validated flag based on the current simple orthogonal transform prototype.

### G. Adversarial/physical acceptance

Protected production release remains blocked until tests cover at least:

- [ ] provider root/admin memory inspection against the declared TEE boundary;
- [ ] core dump / swap / pagefile attempts;
- [ ] MITM and wrong TLS endpoint;
- [ ] stale/wrong/replayed attestation;
- [ ] debug-enabled confidential hardware;
- [ ] runtime substitution;
- [ ] X25519 recipient-key substitution;
- [ ] metering-key substitution;
- [ ] replayed request envelope;
- [ ] reordered/replayed streaming frame;
- [ ] crash after protected completion but before ledger capture;
- [ ] crash after ledger capture but before session acknowledgement;
- [ ] scan proving no protected plaintext in ordinary logs, DBs, replay/session stores or billing journal.

## Documentation freshness requirement

Documentation is part of the P0 security boundary because stale documents can cause operators or developers to deploy the wrong path or make false guarantees.

Every material P0 milestone must update, in the same branch/PR as applicable:

- `docs/P0_CONFIDENTIAL_EXECUTION_PLAN.md`;
- `docs/CURRENT_STATUS.md` and `.de.md`;
- `docs/PRIVACY_TIERS.md`;
- `THREAT_MODEL.md` / `SECURITY.md` when trust or release boundaries change;
- `README.md` / `README.de.md` when public-facing status changes;
- the active private P0 handoff/status document;
- deployment/setup/operator docs when configuration changes.

Do not defer those updates until the end of the workstream.

## Definition of done

`CONFIDENTIAL` is production-ready only when the complete live path can produce content-free evidence that every mandatory protection was active, the local client independently verifies the vendor evidence and bound endpoint/key identities, and physical/adversarial negative testing demonstrates that falsifying or removing any mandatory protection causes fail-closed rejection before protected plaintext is exposed.

`CRYPTO_PRIVATE` has a separate definition of done and must remain unavailable until its cryptographic construction is independently validated.
