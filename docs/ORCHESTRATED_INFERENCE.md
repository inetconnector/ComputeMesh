# Orchestrated Inference Lifecycle

## Status

This is an intermediate integration tranche between the public gateway/runtime bridge and fully verified scheduler-driven shared execution.

The `orchestrated_openai` backend binds each gateway inference to the durable orchestrator job and reservation state machines. Reservations can be derived from a schema-valid M1 scheduler placement decision. Scheduler-derived mode now additionally requires matching `shared_run_evidence` before the job may complete and before provider shares may enter the ledger.

This still does **not** claim cryptographic attestation or production-ready shared scheduling. The current M1 evidence is structurally and content-bound verification of an experimental llama.cpp RPC proof, not a hardware root-of-trust.

## Invariants enforced

A runtime call may start only after the job has progressed through validation/planning/reservation/preparation and every selected provider node has a durable capacity reservation that is leased, committed to the job/stage, and activated.

Successful scheduler-derived execution progresses:

`CREATED -> VALIDATING -> PLANNING -> RESERVING -> PREPARING -> RUNNING -> VERIFYING -> evidence binding -> COMPLETED`

Runtime or evidence-verification failure progresses the active job to `FAILED`. Capacity reservations are released after both success and failure.

The backend requires at least two distinct provider nodes so this mode cannot silently degrade into a single-node orchestration proof.

## Scheduler-derived experimental placement and execution evidence

The preferred integration path is to feed both the JSON produced by `services.scheduler.placement.build_placement_decision()` and the matching proof produced by `runtime.llama.shared_run_evidence` into the orchestrated backend:

```text
COMPUTEMESH_INFERENCE_BACKEND=orchestrated_openai
COMPUTEMESH_INFERENCE_URL=http://127.0.0.1:8080
COMPUTEMESH_ORCHESTRATOR_STATE_PATH=/var/lib/computemesh/orchestrator.sqlite3
COMPUTEMESH_ORCHESTRATOR_PLACEMENT_DECISION=/var/lib/computemesh/placement.json
COMPUTEMESH_ORCHESTRATOR_SHARED_RUN_EVIDENCE=/var/lib/computemesh/shared-run-evidence.json
COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT=1
COMPUTEMESH_ORCHESTRATOR_LEASE_SECONDS=180
```

The placement adapter validates the decision against `placement_decision.schema.json` and fails closed unless:

- the recommendation is `shared_experiment`;
- every hard constraint passed;
- exactly one `shared_contiguous_layers` candidate is feasible;
- the selected layer ranges contain distinct nodes, are contiguous, start at layer zero and cover the complete model;
- the layer-range node IDs exactly match the coordinator/worker IDs in the decision;
- the gateway request model matches the model ID in the placement decision; and
- experimental shared placement is explicitly enabled.

The evidence verifier then fails closed unless:

- the document validates against `shared_run_evidence.schema.json`;
- its evidence ID recomputes from its bound source digests and comparison fields;
- `placement_decision_id` matches the decision that drove the reservations;
- the immutable model artifact digest matches the placement artifact;
- evidence layer ranges exactly match the scheduler-selected layer ranges;
- the SHA-256 of the just-returned runtime text matches `shared_output_sha256`;
- the evidence timestamp plausibly belongs to the current execution window; and
- evidence participants equal the reserved provider nodes.

After verification, provider shares are derived from the number of model layers assigned to each verified provider. The evidence document SHA-256 and evidence ID are durably bound to the orchestrator job in a single-use SQLite extension table. Both fields are unique, so the same proof cannot be replayed to settle a second job.

The `BackendResult` carries the durable orchestrator `execution_job_id` plus the evidence-derived provider shares. `InferenceEngine` uses that orchestrator job ID as the ledger event ID and gives verified shares precedence over `COMPUTEMESH_PROVIDER_SHARES`.

The explicit experimental opt-in remains mandatory because the current M1 placement schema deliberately fixes `recommendation.production_scheduling` to `false`.

## Static lab fallback

For controlled development without a placement artifact, operator-selected nodes remain available:

```text
COMPUTEMESH_ORCHESTRATOR_PROVIDER_NODES=node-a,node-b
```

This path should not be described as scheduler-selected or evidence-derived placement. It retains legacy provider-share behavior and is not the preferred settlement path.

`COMPUTEMESH_INFERENCE_API_KEY` and `COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS` retain their OpenAI-compatible backend meanings.

## Remaining limitations / next tranche

The new binding closes the software path from a matching M1 shared-runtime proof into provider settlement, but two major limitations remain.

First, the placement decision and evidence are still supplied as artifacts rather than generated as one atomic per-request runtime protocol. A real deployment should make the shared runtime/worker layer emit or publish the evidence for the exact current request before the orchestrator completes verification.

Second, M1 evidence is not cryptographic node attestation. Its digests detect mutation and the single-use registry prevents replay inside this state store, but an attacker able to fabricate all source artifacts could fabricate a self-consistent proof. Production settlement therefore still requires signed node identities/evidence or another authenticated attestation mechanism.

The intended next sequence is:

1. generate placement dynamically from current registry/benchmark state at job planning time;
2. make dispatch launch the planner-selected llama.cpp RPC topology directly;
3. make each participating node sign execution evidence tied to job ID, model digest and runtime build;
4. verify those signatures before ledger settlement;
5. add cancellation/timeout/node-loss integration tests around real shared dispatch; and
6. replace post-hoc word splitting with upstream runtime streaming.
