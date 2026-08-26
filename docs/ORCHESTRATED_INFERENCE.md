# Orchestrated Inference Lifecycle

## Status

This is an intermediate integration tranche between the public gateway/runtime bridge and fully verified scheduler-driven shared execution.

The `orchestrated_openai` backend binds each gateway inference to the durable orchestrator job and reservation state machines. Reservations can now be derived from a schema-valid M1 scheduler placement decision instead of a static provider list. It still does **not** claim cryptographically verified execution or production-ready shared scheduling.

## Invariants enforced

A runtime call may start only after the job has progressed through validation/planning/reservation/preparation and every selected provider node has a durable capacity reservation that is leased, committed to the job/stage, and activated.

Successful execution progresses:

`CREATED -> VALIDATING -> PLANNING -> RESERVING -> PREPARING -> RUNNING -> VERIFYING -> COMPLETED`

Runtime failure progresses the active job to `FAILED`. Capacity reservations are released after both success and failure.

The backend requires at least two distinct provider nodes so this mode cannot silently degrade into a single-node orchestration proof.

## Scheduler-derived experimental placement

The preferred integration path is to feed the JSON produced by `services.scheduler.placement.build_placement_decision()` into the orchestrated backend:

```text
COMPUTEMESH_INFERENCE_BACKEND=orchestrated_openai
COMPUTEMESH_INFERENCE_URL=http://127.0.0.1:8080
COMPUTEMESH_ORCHESTRATOR_STATE_PATH=/var/lib/computemesh/orchestrator.sqlite3
COMPUTEMESH_ORCHESTRATOR_PLACEMENT_DECISION=/var/lib/computemesh/placement.json
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

The explicit opt-in is mandatory because the current M1 schema deliberately fixes `recommendation.production_scheduling` to `false`.

## Static lab fallback

For controlled development without a placement artifact, operator-selected nodes remain available:

```text
COMPUTEMESH_ORCHESTRATOR_PROVIDER_NODES=node-a,node-b
```

This path should not be described as scheduler-selected placement.

`COMPUTEMESH_INFERENCE_API_KEY` and `COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS` retain their OpenAI-compatible backend meanings.

The runtime URL can point to a llama.cpp-compatible endpoint whose process is configured to use RPC workers. The orchestration layer proves durable control-plane admission/reservation around that invocation; it does not yet prove that the nodes named by the placement decision are exactly the devices that performed the runtime work.

## Explicit limitations / next tranche

Scheduler-derived reservations are now available, but the placement decision itself is still M1 experimental evidence and is loaded as an artifact rather than being generated dynamically for every gateway job.

Before billing can be considered placement-derived, the runtime must return execution evidence binding the actual participating node identities and model/runtime hashes to the completed job. Provider payout shares should then come from that verified evidence, not from gateway environment configuration.

The intended next sequence is:

1. generate/refresh placement decisions from current node profiles and benchmark evidence at job planning time;
2. dispatch the planner-selected shared runtime, not merely wrap a preconfigured runtime endpoint;
3. attach and verify `shared_run_evidence` against the job, placement decision, model digest and runtime identity;
4. derive provider payout shares only from verified participating nodes;
5. add cancellation/timeout/node-loss integration tests around real shared dispatch; and
6. replace post-hoc word splitting with upstream runtime streaming.
