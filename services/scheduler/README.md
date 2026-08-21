# Scheduler and Topology Service

**Status:** deterministic M1 two-node feasibility planner implemented; production scheduler not implemented.

## Purpose

`services/scheduler/placement.py` turns current measured evidence into an explainable **experiment placement candidate** for the narrow two-node llama.cpp M1 proof.

It is deliberately conservative. It answers: *is a local baseline or a contiguous two-node layer experiment memory-feasible under the evidence and policy supplied?* It does **not** pretend that independent node benchmarks plus network bandwidth are enough to predict shared-runtime speed.

## Inputs and evidence binding

The planner consumes existing repository contracts:

- coordinator `node_profile.schema.json`;
- worker `node_profile.schema.json`;
- `model_manifest.schema.json`;
- coordinator llama-bench prefill + decode records;
- worker llama-bench prefill + decode records;
- coordinator → worker TCP network benchmark;
- optional exact artifact digest when a manifest has multiple artifacts.

New M1 evidence can carry two facts directly:

- `model_manifest.layer_count` — the planner records `layer_count_source = model_manifest_v1`;
- network benchmark `conditions.local_node_id`, `peer_node_id`, and `peer_identity_binding` — the planner verifies the local ID against the coordinator and the peer ID against the worker.

The current benchmark server reports its Lab Setup node ID with binding label `unauthenticated_server_report_v1`. That is **traceability, not authentication**: the benchmark protocol still has no application authentication or encryption and remains trusted-private-LAN-only.

Backward compatibility is explicit rather than silent. Older model manifests may still use `--layer-count`; older network benchmark records may still use `--network-peer-node-id`. Those decisions are labelled `caller_asserted_v1`. If embedded evidence and a caller fallback are both supplied, they must agree exactly.

## Hard checks

Before producing candidates, the planner rejects or marks infeasible:

- invalid profile/model/benchmark schemas;
- same node ID used for both roles;
- embedded network local-node ID not equal to the coordinator profile;
- embedded or caller-asserted network peer ID not equal to the worker profile;
- caller peer assertion conflicting with an embedded peer ID;
- caller layer count conflicting with manifest `layer_count`;
- missing layer count when neither manifest nor legacy argument supplies it;
- benchmark type mismatch;
- benchmark profile revision not equal to the corresponding current node-profile revision;
- inconsistent model basename across llama benchmarks;
- benchmark model size not equal to the selected manifest artifact size;
- manifest without `contiguous_layers` permission;
- stale/future-skewed node profiles;
- draining nodes for the candidate that needs them.

A stale or draining worker blocks the shared candidate but does not invalidate an otherwise valid local coordinator baseline. A stale/draining coordinator blocks both.

## Memory feasibility model

This first planner selects the largest reported GPU/accelerator memory device on each node; if no accelerator with memory exists, it uses currently available system RAM as a CPU fallback.

Usable memory is bounded by the smaller of:

- the node's `provider_limits.max_memory_fraction` (or 1.0 if absent), and
- planner policy `planner_memory_fraction` (default 0.90).

For the shared candidate, the selected model artifact is modeled as:

- fixed coordinator overhead fraction (default 10%);
- the remaining bytes spread uniformly over the resolved layer count.

This is a **conservative M1 planning approximation**, not a claim that real GGUF tensors are perfectly uniform by layer. The actual llama.cpp run remains the authority. A shared candidate is emitted only when at least one layer fits on each node and all layers fit across the two conservative budgets.

The generated ranges are contiguous and cover `[0, layer_count)` exactly. The same layer counts are emitted as relative `tensor_split` weights for the controlled experiment.

## Performance evidence boundary

The decision records measured:

- coordinator prefill/decode tok/s;
- worker prefill/decode tok/s;
- RTT p50/p95;
- upload/download p50 throughput.

But until a correct measured shared run exists, it always emits:

```text
performance_evidence.status = insufficient_shared_runtime_evidence
predicted_shared_request_ms = null
predicted_speedup_vs_local = null
```

This prevents the first scheduler prototype from converting unrelated local benchmarks into fabricated distributed-performance claims.

## Recommendation modes

- `shared_experiment` — a conservative two-node contiguous-layer candidate is memory-feasible; run and compare it, but do not treat it as a production ranking.
- `local_only` — shared placement is unavailable under current hard/memory constraints, while local baseline remains feasible.
- `no_plan` — no candidate satisfies current hard constraints and conservative memory feasibility.

Every decision has `production_scheduling = false`.

## Determinism

`decision_id` is derived from the model digest, node IDs/profile revisions, exact benchmark run IDs, resolved layer count and its evidence source, network-peer binding source, and planner policy. Re-running the same evidence/policy yields the same decision ID. The capture timestamp is observational and is not part of that identity.

## CLI

For new bound evidence, neither peer ID nor layer count needs a separate argument:

```bash
python -m services.scheduler.placement \
  --coordinator-profile artifacts/node-a/node_profile.json \
  --worker-profile artifacts/node-b/node_profile.json \
  --model-manifest model_manifest.json \
  --coordinator-prefill artifacts/node-a/prefill.json \
  --coordinator-decode artifacts/node-a/decode.json \
  --worker-prefill artifacts/node-b/prefill.json \
  --worker-decode artifacts/node-b/decode.json \
  --network artifacts/node-a/network-to-b.json \
  --output artifacts/m1/placement.json
```

For legacy artifacts only, add `--network-peer-node-id node-b` and/or `--layer-count 32` as needed. When the manifest has multiple artifacts, pass the exact `--artifact-digest sha256:...`.

Result contract: `services/scheduler/placement_decision.schema.json`.

## Tests

```bash
python -m unittest discover -s services/scheduler/tests -v
```

Coverage includes schema validation, deterministic decision IDs, contiguous complete ranges, draining/stale behavior, memory fallback/no-plan behavior, profile-revision binding, model-size binding, embedded and legacy network-peer binding, local-node binding, embedded/caller conflict rejection, manifest/legacy layer-count resolution, manifest partition permission, CPU-memory fallback and the explicit no-speedup-prediction boundary.

## Non-goals / remaining work

This is not yet:

- a production scheduler;
- a multi-node/general topology optimizer;
- a cost/energy optimizer;
- an authorization or reservation decision;
- a runtime executor;
- an activation-size predictor;
- a learned latency model;
- evidence that the proposed layer split is actually faster.

After the first correct measured shared run, the next scheduler step is to ingest that exact shared-runtime/relay evidence and calibrate prediction/ranking rather than inventing a formula in advance.
