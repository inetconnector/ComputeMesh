# Verification and Reputation

**Status:** public execution-evidence/attestation verification implemented; standalone public verification service remains incomplete; production reputation/fraud policy is private.

## Purpose

Attach evidence-backed verification to execution and provide bounded trust inputs without claiming cryptographic proof of arbitrary inference correctness.

## Current implemented foundations

The current public live path includes:

- bounded execution-evidence records;
- authenticated provider execution-attestations bound to enrolled Ed25519 identities/sessions;
- verification before successful measured outcomes are accepted for private feedback;
- failure handling that distinguishes ordinary runtime failure from explicitly invalid evidence;
- billing/recovery integration that does not treat unverified provider self-report as authoritative completion.

Production reputation state, fraud thresholds/signals and placement eligibility policy live in the private `ComputeMesh-ControlPlane` repository. Public responses must not expose raw reputation/fraud features or score decomposition.

## Future verification responsibilities

- risk classification
- canaries/server-generated challenges
- sampled redundancy
- trace/challenge rules where supported by the runtime
- disagreement handling
- richer immutable verification results
- confidence/decay semantics for trust evidence

## Non-goals

- claiming cryptographic proof without one
- making confidentiality guarantees
- overriding scheduler hard privacy constraints
- publishing private fraud/reputation internals

## Canonical interfaces

- live orchestrator/execution evidence
- private production placement/reputation/fraud services
- billing/settlement eligibility
- future telemetry/operations read models

## Current readiness gap

Current attestation verifies which enrolled provider signed a bounded execution statement; it does not by itself prove that every tensor/token was computed correctly on an uncompromised host. Broader canary/redundancy/challenge policy and adversarial physical validation remain open.

## Required tests / evidence

- valid/invalid attestation signatures and identity binding
- replay/session/revision mismatch
- duplicate outcome delivery
- disagreement/canary policy when implemented
- reputation confidence/decay privately
- failure versus fraud classification
- privacy of trust/fraud features

## Security and reliability rules

- Treat all provider evidence as untrusted until validated.
- Use bounded messages/resources.
- Preserve idempotency for state changes/outcome ingestion.
- Emit structured errors without raw prompt/output content.
- Do not expose private scoring/fraud thresholds.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

See `services/orchestrator/README.md`, `apps/node/README.md`, `docs/CURRENT_STATUS.md` and the private control-plane documentation for the implemented boundary.
