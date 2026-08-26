# Orchestrated Inference Lifecycle

## Status

The `orchestrated_openai` backend binds gateway inference to the durable orchestrator job/reservation state machines, scheduler placement, shared-run evidence, and Ed25519 participant attestations.

Scheduler-derived provider settlement is now fail-closed unless the current runtime output is backed by matching `shared_run_evidence` **and every reserved provider node signs the exact execution tuple with an active enrolled ComputeMesh node key**.

This is still experimental M1 scheduling rather than production hardware attestation. The signatures authenticate enrolled node identities and their claims; they do not prove a TEE/TPM measurement or make a compromised node truthful.

## Successful scheduler-derived lifecycle

`CREATED -> VALIDATING -> PLANNING -> RESERVING -> PREPARING -> RUNNING -> VERIFYING -> evidence verification -> participant signature verification -> durable evidence binding -> COMPLETED -> ledger settlement`

Runtime, evidence, identity, or attestation verification failure moves the active job to `FAILED`. Capacity is released after success and failure.

## Configuration

```text
COMPUTEMESH_INFERENCE_BACKEND=orchestrated_openai
COMPUTEMESH_INFERENCE_URL=http://127.0.0.1:8080
COMPUTEMESH_ORCHESTRATOR_STATE_PATH=/var/lib/computemesh/orchestrator.sqlite3
COMPUTEMESH_ORCHESTRATOR_PLACEMENT_DECISION=/var/lib/computemesh/placement.json
COMPUTEMESH_ORCHESTRATOR_SHARED_RUN_EVIDENCE=/var/lib/computemesh/shared-run-evidence.json
COMPUTEMESH_ORCHESTRATOR_EXECUTION_ATTESTATIONS=/var/lib/computemesh/execution-attestations.json
COMPUTEMESH_IDENTITY_STATE_PATH=/var/lib/computemesh/identity.sqlite3
COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT=1
COMPUTEMESH_ORCHESTRATOR_LEASE_SECONDS=180
```

The experimental opt-in remains mandatory because the current M1 placement schema fixes `recommendation.production_scheduling=false`.

## Placement and evidence checks

The placement adapter fails closed unless all hard constraints pass, exactly one feasible `shared_contiguous_layers` candidate is selected, its node IDs match coordinator/worker identities, and layer ranges form a complete contiguous model assignment.

The shared-run evidence verifier then checks schema validity, recomputed evidence ID, placement ID, immutable model digest, exact scheduler layer ranges, current output SHA-256, execution time window, and participant equality. It also derives a canonical SHA-256 of the evidence `runtime` object, so the runtime identity becomes part of the signed settlement tuple.

Provider shares are derived from verified layer counts. Evidence ID and evidence document SHA-256 are durably single-use-bound to the orchestrator job, preventing reuse of one proof for a second settlement.

## Signed execution attestations

Each reserved node must provide one Ed25519 signature using an active key already registered in `SQLiteIdentityStore`. The verifier requires the attestation set to exactly equal the reserved node set and binds each signature to:

- `node_id` and `key_id`
- `job_id`
- `placement_decision_id`
- `model_sha256`
- canonical `runtime_sha256`
- `evidence_sha256`
- `output_sha256`
- bounded `issued_at` / `expires_at`

The signature domain is `ComputeMesh.ExecutionAttestation.v1`, separate from the existing node-session authentication domain. Revoked/unknown keys, missing participants, duplicates, stale attestations, altered claims, or invalid signatures fail verification before evidence is bound and before provider shares reach the ledger.

Node private keys remain node-local; the gateway verifier consumes only enrolled public keys through the existing identity resolver.

## Static lab fallback

Without a placement artifact, operator-selected nodes remain available for controlled lab work:

```text
COMPUTEMESH_ORCHESTRATOR_PROVIDER_NODES=node-a,node-b
```

This path is not scheduler-selected, evidence-derived, or signed-settlement proof and retains legacy provider-share behavior.

## Remaining limitations / next tranche

The control-plane settlement trust chain is now authenticated, but two major gaps remain:

1. Placement, shared-run evidence, and the attestation bundle are still supplied as artifacts rather than emitted atomically by a per-job shared execution protocol.
2. Ed25519 proves that the enrolled node key signed the claims, not that untampered hardware executed them.

Next work should therefore make the planner-selected RPC dispatch create the current job-specific evidence and node attestations automatically, add cancellation/timeout/node-loss tests, then add optional hardware-backed attestation where available and replace post-hoc gateway word splitting with upstream streaming.
