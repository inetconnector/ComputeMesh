# ComputeMesh current public status

**Current as of:** 2026-09-03

This document is the public-safe status summary. It is intentionally separate from the private `ComputeMesh-ControlPlane/STATE.md`, which contains proprietary placement, ranking and operational details.

## Status discipline

Every statement below distinguishes between:

- **merged** behavior on public `main`;
- **branch-local draft** behavior on an open PR;
- **software/CI validation**;
- **physical/adversarial validation**;
- **production guarantees**.

A branch-local implementation or green CI is not a production confidentiality claim.

## What exists today

ComputeMesh is an active pre-production distributed-inference system with real implementations for:

- authenticated provider-control sessions and Ed25519 node identity/enrollment reference state;
- a runnable public provider agent that authenticates, publishes measured profile/runtime/benchmark evidence, reconnects and answers authenticated control requests;
- OpenAI/Ollama-compatible gateway surfaces, model catalog handling, billing foundations and durable orchestration state;
- private production placement/recovery integration through bounded signed interfaces while proprietary ranking/reputation/fraud/pricing logic remains private;
- a real llama.cpp shared-runtime research path with recorded physical two-machine evidence for a narrow tested topology;
- global mesh trust/privacy policy with `OPEN` / `VERIFIED` / `RESTRICTED` provider trust tiers and `PUBLIC` / `CONFIDENTIAL` / `CRYPTO_PRIVATE` execution privacy classes;
- signed/replay-aware protocol, identity, accounting and updater foundations.

## P0 confidential-execution state

### Merged public foundations

The following P0 foundations are merged to public `main`:

- PR #72 — central fail-closed protected-execution foundation;
- PR #73 — attestation-bound X25519/HKDF/AES-256-GCM confidential payload envelope foundation;
- PR #74 — hash-pinned NVIDIA confidential-attestation verifier-process boundary;
- secure-memory primitives with explicit zeroization and optional mandatory page locking;
- POSIX dumpability/core-dump hardening primitive;
- request-scoped attestation and key-release contracts.

### Open draft PR #76 — `security/p0-confidential-metering`

PR #76 is **open and draft**. It must not be described as merged or production-ready.

The branch currently contains substantially more than the earlier session/metering prototype, including:

- durable confidential session state with `OPEN -> DISPATCHED -> METERED -> COMPLETED` plus failure handling;
- content-free Ed25519 usage receipts bound to account/job/request/response/node/runtime/privacy/operation/model/token counts;
- durable double-entry confidential escrow and restart/idempotency recovery;
- authenticated confidential-envelope binding that includes model and prompt/completion token budgets;
- a loopback-only OpenAI-compatible local protected proxy so plaintext can be encrypted before remote network egress;
- bidirectional encrypted protected responses and authenticated protected streaming that is converted locally back to normal OpenAI SSE;
- durable request replay tombstones and TLS-pinned protected data-plane clients;
- a pure protected-transport gateway mixin and a canonical unified live handler composition rather than a competing second public server;
- a remote confidential-session broker client that sends only content-free admission metadata to the private control plane and accepts only a reduced provision result;
- a provider-control confidential provisioning handler that runs over an already authenticated provider `NodeSession` and rejects stale session revisions, wrong node identity, missing capability negotiation and unavailable models;
- a dedicated protected-worker implementation with request-scoped X25519 recipient material, Ed25519 metering identity, replay validation, exact session/envelope binding, protected-memory controls, encrypted response handling and content-free metering;
- a dedicated HTTPS worker boundary instead of treating raw public llama.cpp RPC as the protected security boundary.

These are **branch-local software foundations**. They do not by themselves prove that a provider operator cannot inspect plaintext on real hardware.

## OpenAI compatibility boundary

The intended user contract remains the standard OpenAI-style surface:

- `POST /v1/chat/completions`;
- `GET /v1/models`;
- standard non-stream completion objects;
- standard SSE completion chunks for `stream=true`.

For `CONFIDENTIAL` / future `CRYPTO_PRIVATE`, the trusted local ComputeMesh transport/proxy is part of the client boundary. It accepts the ordinary OpenAI-shaped request locally, verifies the protected provision/attestation policy, encrypts the original request before remote egress, then decrypts and validates the protected response locally.

The internal `/internal/v1/confidential/...` routes are transport internals, not a second public API. Legacy public `/v1/confidential/...` aliases are not the intended product interface.

## Public/private production boundary

Production ranking and policy do **not** belong in the public reference scheduler.

The private `inetconnector/ComputeMesh-ControlPlane` repository owns proprietary production placement/ranking, empirical performance state, reputation/fraud policy, marketplace/pricing policy and private recovery/settlement policy. The public repository owns the portable protocol/runtime/gateway/client/provider mechanisms needed to execute a reduced approved result.

For confidential admission, the public-side branch now contains the remote broker contract and authenticated provider-control provisioning handler. The remaining production task is to wire the private confidential-provision service through the existing authenticated provider-control channel to the selected protected worker, without exposing losing candidates, scores, fraud/reputation features or pricing coefficients.

## What is validated vs. what is not

### Validated in software/tests on the development branches

- protected request/response envelope binding and replay behavior;
- local protected OpenAI proxy behavior;
- encrypted streaming sequencing/finalization behavior;
- confidential session state and metering receipts;
- double-entry confidential escrow and idempotent recovery;
- unified protected gateway composition;
- reduced remote confidential-broker parsing/validation;
- protected-worker and provider-control fail-closed contracts.

### Physically validated

- a narrow historical trusted-lab two-machine shared llama.cpp proof for its exact recorded hardware/model/runtime/topology.

### Not yet a production confidentiality guarantee

- real supported NVIDIA confidential-compute hardware with the final vendor SDK/helper path;
- physical validation of nonce, measurement, CC/debug state and bound protected endpoint/key identities on that hardware;
- hostile-provider/root/admin memory-inspection acceptance against the declared TEE boundary;
- complete production bootstrap and private confidential-provision deployment across real selected providers;
- full MITM/replay/substitution/core-dump/swap/pagefile adversarial acceptance;
- AMD confidential execution for any concrete topology;
- a validated `CRYPTO_PRIVATE` cryptographic construction;
- broad heterogeneous multi-node production inference and HA/operations readiness.

## Important security boundaries

- `PUBLIC` compute may expose workload plaintext to the provider runtime and is not confidential execution.
- TLS, SSH, containers, VMs, ordinary sharding and page locking do not by themselves provide confidential execution.
- raw/upstream llama.cpp RPC remains an experimental trusted-network development component and is not the protected public security boundary.
- `CONFIDENTIAL` must fail closed when the complete required chain is unavailable.
- `CRYPTO_PRIVATE` must remain unavailable until its cryptographic construction is independently validated.
- CI success must never be represented as physical TEE acceptance.

## Primary engineering entry points

- `docs/CURRENT_STATUS.md` / `docs/CURRENT_STATUS.de.md` — current public-safe status;
- `docs/P0_CONFIDENTIAL_EXECUTION_PLAN.md` — current P0 architecture, completed foundations and remaining release gates;
- `THREAT_MODEL.md` and `SECURITY.md` — security boundaries and release blockers;
- `docs/PRIVACY_TIERS.md` — enforced execution-privacy semantics;
- `CONTRIBUTING.md` — definition of done, including the documentation-freshness invariant;
- `state.md` — detailed public historical engineering log;
- `services/gateway/protected_transport_mixin.py` / `unified_live_handler.py` — branch-local protected gateway composition;
- `services/orchestrator/remote_confidential_broker.py` — public reduced private-control-plane client;
- `runtime/confidential/provider_control.py` / `protected_worker.py` / `worker_http.py` — provider-side protected admission and worker boundary.

## Immediate readiness work

The next P0 gate is the real end-to-end confidential provisioning/deployment chain, not more protocol scaffolding:

1. finish the private confidential-provision service and connect it to the already authenticated provider-control session;
2. complete live protected bootstrap/configuration so confidential readiness is false unless broker, session/replay stores, escrow, verifier policy and data planes are all installed;
3. keep the standard OpenAI-compatible user surface while protected transport remains internal;
4. build and hash-pin the real vendor-supported NVIDIA attestation helper and validate it on supported confidential-compute hardware;
5. run physical/adversarial acceptance before any production confidentiality claim;
6. keep all authoritative documentation synchronized with every material milestone.
