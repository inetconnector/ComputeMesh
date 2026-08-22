# Scheduler and Topology Service

**Status:** deterministic M1 two-node feasibility planner plus fail-closed current-evidence bundle preparation implemented; production scheduler not implemented.

## Purpose

`services/scheduler/placement.py` turns current measured evidence into an explainable **experiment placement candidate** for the narrow two-node llama.cpp M1 proof.

It is deliberately conservative. It answers: *is a local baseline or a contiguous two-node layer experiment memory-feasible under the evidence and policy supplied?* It does **not** pretend that independent node benchmarks plus network bandwidth are enough to predict shared-runtime speed.

`services/scheduler/evidence_bundle.py` is the engineering preparation layer in front of that planner. It searches two explicitly supplied Lab evidence roots, selects one coherent current evidence set, invokes the same placement planner without legacy peer/layer fallbacks, and emits one provenance-bound experiment bundle.

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

Backward compatibility in `placement.py` is explicit rather than silent. Older model manifests may still use `--layer-count`; older network benchmark records may still use `--network-peer-node-id`. Those decisions are labelled `caller_asserted_v1`. If embedded evidence and a caller fallback are both supplied, they must agree exactly.

The **experiment-bundle path intentionally does not offer those compatibility arguments**. It requires manifest layer evidence plus an embedded coordinator→worker peer binding so a bundle intended for the current real experiment cannot quietly fall back to manual assertions.

## Current experiment evidence bundle

Given two copied/exported Lab evidence trees and one model manifest, the bundle helper:

1. scans only JSON files below the two explicit roots, with file-count/file-size bounds and no symlink following;
2. schema-validates anything that looks like a node profile or benchmark result;
3. requires one node identity per role unless the caller explicitly selects a node ID;
4. selects the highest profile revision for each role and rejects conflicting documents at that revision;
5. requires `model_manifest.layer_count` and selects the exact manifest artifact;
6. considers only prefill/decode runs whose profile revision matches the selected node profile, whose model size equals the selected manifest artifact, and whose capture timestamp is not earlier than that profile;
7. requires one common model basename with a complete prefill/decode pair on both nodes, or explicit `--benchmark-model-name` disambiguation;
8. selects the newest unique run for each required benchmark type and rejects equally recent distinct candidates;
9. requires a coordinator→worker TCP record with matching current coordinator revision plus embedded `local_node_id` and `peer_node_id` in the correct direction;
10. invokes `build_placement_decision` with no legacy peer/layer arguments;
11. rejects any resulting `caller_asserted_v1` network binding;
12. emits one schema-valid bundle containing the placement decision and source provenance.

Provenance records contain only safe source basenames plus SHA-256 of the exact JSON documents, run IDs/node revisions and model artifact identity. Absolute local paths are never included. `bundle_id` is deterministic for the same source documents and placement decision.

This is still **engineering evidence packaging**, not cryptographic attestation: hashing the copied JSON files makes the selected input set reproducible, but it does not prove who originally produced those files.

### Bundle CLI

Example after copying the two machines' Lab evidence directories to one analysis machine:

```bash
python -m services.scheduler.evidence_bundle \
  --coordinator-root imported/node-a-lab \
  --worker-root imported/node-b-lab \
  --model-manifest artifacts/model.computemesh-model-manifest.json \
  --output artifacts/m1/experiment-bundle.json
```

Optional disambiguators are deliberately evidence selectors rather than legacy assertions:

- `--coordinator-node-id` / `--worker-node-id` when an imported root contains more than one node;
- `--benchmark-model-name` when multiple model basenames have complete matching runs at the selected artifact size;
- `--network-run-id` to pin one already-bound coordinator→worker network run;
- `--artifact-digest` when the manifest contains more than one artifact.

Result contract: `services/scheduler/experiment_bundle.schema.json`.

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

`bundle_id` additionally binds SHA-256 of the eight selected source JSON documents to that decision identity. The bundle capture timestamp is likewise observational rather than part of bundle identity.

## Direct placement CLI

For explicitly selected new bound evidence, neither peer ID nor layer count needs a separate argument:

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

Placement result contract: `services/scheduler/placement_decision.schema.json`.

## Tests

```bash
python -m unittest discover -s services/scheduler/tests -v
```

Placement coverage includes schema validation, deterministic decision IDs, contiguous complete ranges, draining/stale behavior, memory fallback/no-plan behavior, profile-revision binding, model-size binding, embedded and legacy network-peer binding, local-node binding, embedded/caller conflict rejection, manifest/legacy layer-count resolution, manifest partition permission, CPU-memory fallback and the explicit no-speedup-prediction boundary.

Bundle coverage additionally includes highest-profile selection, multi-node-root rejection/disambiguation, wrong/legacy network direction rejection, pre-profile benchmark rejection, exact artifact-size filtering, common-model selection, ambiguous latest-run rejection, corrupt evidence fail-closed behavior, deterministic provenance identity, schema validation, absolute-path non-disclosure, and rejection of caller-asserted peer binding from the current bundle path.

## Non-goals / remaining work

This is not yet:

- a production scheduler;
- a multi-node/general topology optimizer;
- a cost/energy optimizer;
- an authorization or reservation decision;
- a runtime executor;
- cryptographically attested evidence provenance;
- automatic transfer/synchronization of evidence between machines;
- an activation-size predictor;
- a learned latency model;
- evidence that the proposed layer split is actually faster.

After the first correct measured shared run, the next scheduler step is to ingest that exact shared-runtime/relay evidence and calibrate prediction/ranking rather than inventing a formula in advance.
