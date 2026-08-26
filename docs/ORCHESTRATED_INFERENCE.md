# Orchestrated Inference Lifecycle

## Status

This is an intermediate integration tranche between the public gateway/runtime bridge and scheduler-driven shared placement.

The `orchestrated_openai` backend binds each successful gateway inference to the durable orchestrator job and reservation state machines. It does **not** yet claim scheduler-selected placement or cryptographic execution verification.

## Invariants enforced

A runtime call may start only after the job has progressed through validation/planning/reservation/preparation and every configured provider node has a durable capacity reservation that is leased, committed to the job/stage, and activated.

Successful execution progresses:

`CREATED -> VALIDATING -> PLANNING -> RESERVING -> PREPARING -> RUNNING -> VERIFYING -> COMPLETED`

Runtime failure progresses the active job to `FAILED`. Capacity reservations are released after both success and failure.

The backend requires at least two distinct provider nodes so this mode cannot silently degrade into a single-node orchestration proof.

## Configuration

```text
COMPUTEMESH_INFERENCE_BACKEND=orchestrated_openai
COMPUTEMESH_INFERENCE_URL=http://127.0.0.1:8080
COMPUTEMESH_ORCHESTRATOR_STATE_PATH=/var/lib/computemesh/orchestrator.sqlite3
COMPUTEMESH_ORCHESTRATOR_PROVIDER_NODES=node-a,node-b
COMPUTEMESH_ORCHESTRATOR_LEASE_SECONDS=180
```

`COMPUTEMESH_INFERENCE_API_KEY` and `COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS` retain their OpenAI-compatible backend meanings.

The runtime URL can point to a llama.cpp-compatible endpoint whose own process is configured to use RPC workers. The orchestration layer here proves durable control-plane admission/reservation around that invocation; it does not yet prove that the configured node list exactly equals the devices used inside that runtime.

## Explicit limitations / next tranche

The provider-node list is currently operator supplied. It must be replaced by the output of `services.scheduler.placement.build_placement_decision()` using current node profiles, benchmarks, network evidence and the selected immutable model artifact.

Before billing can be considered placement-derived, the runtime must return execution evidence binding the actual participating node identities and model/runtime hashes to the completed job. Provider payout shares should then come from that verified evidence, not from gateway environment configuration.

The intended next sequence is:

1. scheduler adapter produces a validated placement decision;
2. reservations are created from that decision rather than a static node list;
3. dispatch launches the planner-selected shared runtime;
4. shared-run evidence is attached to the job and verified;
5. only verified participating nodes are passed to ledger settlement;
6. post-hoc word splitting is replaced with upstream runtime streaming.
