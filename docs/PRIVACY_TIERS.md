# ComputeMesh Privacy Tiers

**Status:** active architecture / pre-production implementation  
**Current as of:** 2026-09-03

Privacy classes are enforceable execution policies. They are not marketing labels.

## 1. General rule

ComputeMesh separates three different concepts:

- transport security;
- provider/location/operator policy;
- execution confidentiality.

Encrypted transport protects data between endpoints. It does not by itself protect plaintext while a provider-controlled runtime is processing it.

The canonical execution-privacy classes are:

- `PUBLIC`;
- `CONFIDENTIAL`;
- `CRYPTO_PRIVATE`.

Provider trust (`OPEN`, `VERIFIED`, `RESTRICTED`) and region/operator restrictions are separate policy dimensions.

## 2. `PUBLIC`

`PUBLIC` is ordinary admitted compute.

Eligible capacity may include community/consumer and approved general providers subject to the separately configured trust, region, model/runtime, network and customer policy.

Security assumption:

- a provider administrator or malware on the host may be able to inspect prompts, activations, KV state, token-related state or outputs available to the runtime.

Required protections still include authenticated transport/control, workload-boundary controls, bounded interfaces and telemetry minimization.

`PUBLIC` does **not** guarantee confidential execution.

## 3. Region/operator/datacenter restrictions

Region, operator and datacenter restrictions constrain where and by whom a job may run. They can reduce contractual or operational risk, but they do not inherently provide cryptographic execution confidentiality.

A job may therefore be both region-restricted and `PUBLIC`, or region-restricted and `CONFIDENTIAL` when a verified confidential-compute topology also satisfies the region policy.

## 4. `CONFIDENTIAL`

`CONFIDENTIAL` requires a real hardware-backed protected-execution chain. It must fail closed when any mandatory part of that chain is missing or unverifiable.

The required production chain includes:

- a supported confidential-compute CPU/GPU/accelerator topology;
- fresh technology-specific remote attestation;
- measured/approved runtime identity;
- debug-disabled/production confidential-compute state where the technology exposes such a distinction;
- attestation-bound ephemeral X25519 recipient key;
- attestation-bound Ed25519 content-free metering key;
- attestation-bound protected data-plane TLS identity;
- request/session binding including account, job, model, privacy class, operation and token budgets;
- authenticated encryption of request and response content;
- replay protection;
- protected-worker memory/process hardening and bounded plaintext lifetime;
- no prompt/output/token-ID/activation logging outside the protected boundary;
- fail-closed settlement based on content-free authenticated usage evidence.

### Current implementation state

Merged public foundations already include fail-closed protected execution, the attestation-bound confidential envelope and the pinned NVIDIA verifier-process boundary.

Open draft PR #76 additionally contains the local protected OpenAI proxy, encrypted response/stream transport, durable confidential sessions, content-free metering, double-entry escrow, unified protected gateway composition, reduced remote confidential broker, authenticated provider-control provisioning handler and dedicated protected-worker HTTPS boundary.

That is substantial software implementation, but it is **not yet a production hardware confidentiality guarantee**. The final vendor-supported NVIDIA attestation helper and physical/adversarial acceptance on supported confidential-compute hardware are still required. AMD confidential execution is not claimed without a concrete proved topology.

The scheduler/gateway MUST reject `CONFIDENTIAL` when the complete required chain is unavailable rather than silently downgrade to `PUBLIC`.

## 5. `CRYPTO_PRIVATE`

`CRYPTO_PRIVATE` is a stronger/different class whose confidentiality must come from a validated cryptographic private-computation construction rather than relying solely on a provider hardware TEE.

Candidate mechanisms may include MPC, secret sharing, FHE or carefully reviewed hybrids.

The current simple orthogonal hidden-state rotation/blinding prototype is research-only and does **not** satisfy this class. `CRYPTO_PRIVATE` must remain unavailable until functional equivalence, threat model and leakage properties are independently validated for the exact construction and runtime.

## 6. Mixed-stage policy

A job's effective privacy is no stronger than its weakest participating stage.

Sensitive jobs must not route any plaintext-bearing stage through `PUBLIC` capacity unless the user explicitly requested a policy that permits that exposure. A protected job must never silently mix in an unprotected stage.

## 7. Logging and evidence

For all privacy classes, default platform logs exclude raw prompts/outputs.

For protected execution, ordinary gateway/control-plane/session/replay/billing stores must additionally exclude reusable content keys, token IDs and semantically useful intermediate state. Protected usage receipts are deliberately content-free.

## 8. User/API behavior

The user-facing application contract remains OpenAI-compatible.

- `PUBLIC` can use the ordinary remote API path.
- `CONFIDENTIAL` uses a trusted local ComputeMesh transport/proxy (or equivalent client-side transport) so plaintext is encrypted before remote network egress.
- internal `/internal/v1/confidential/...` routes are transport internals, not a second public application API.

If requested privacy cannot be satisfied:

- reject with a machine-readable/OpenAI-shaped error as appropriate;
- never silently relax privacy;
- never claim that TLS, SSH, containers, VMs, page locking or ordinary sharding alone satisfy `CONFIDENTIAL`;
- never claim CI success as physical TEE validation.
