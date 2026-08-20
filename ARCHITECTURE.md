# ComputeMesh Architecture

**Status:** Draft v0.2  
**Scope:** target V1 architecture and M0/M1 implementation constraints  
**Normative language:** `MUST`, `MUST NOT`, `SHOULD`, and `MAY` indicate intended architectural requirements.

## 1. Purpose

ComputeMesh is a distributed inference fabric. Its job is to convert a user request plus a model and policy into a concrete, auditable execution plan across heterogeneous capacity.

The architecture is optimized for five realities:

1. network links are slower and less predictable than GPU-local interconnect;
2. provider hardware is heterogeneous;
3. consumer/provider nodes can disappear without notice;
4. some providers may be faulty or malicious;
5. model execution has different resource behavior during prefill and decode.

The system therefore MUST optimize the **whole execution path**, not individual GPUs.

## 2. Architectural invariants

- V1 MUST NOT execute arbitrary customer code on provider hosts.
- Workload admission MUST be model/runtime aware.
- The scheduler MUST evaluate hard constraints before ranking feasible plans.
- Every state-changing command MUST be idempotent or carry an idempotency key.
- Capacity MUST be leased/reserved before job dispatch to avoid placement races.
- Model artifacts MUST be immutable and content-addressed.
- Billing MUST derive from auditable execution events, not provider self-report alone.
- Privacy policy MUST be an enforceable placement constraint.
- A provider node MUST be able to drain without accepting new work.
- Recovery MUST never silently continue from unverified or ambiguous state.
- Telemetry MUST avoid prompt/output content by default.

## 3. Logical node types

### 3.1 Client

The client submits prompts or embeddings requests and receives streamed results. A client MAY also be a provider, but the roles are logically separate.

### 3.2 Provider node

A provider node contributes one or more execution devices and local storage. V1 targets Windows first, but protocol contracts MUST remain OS-neutral.

### 3.3 Datacenter provider

A datacenter provider is a provider node or cluster with stronger availability, network, operational, and possibly confidentiality guarantees.

### 3.4 Control-plane service

Control-plane services authenticate, plan, reserve, audit, meter, verify, and settle work.

### 3.5 Relay/edge service

A future relay MAY terminate authenticated tunnels, improve NAT traversal, or aggregate regional traffic. Relays MUST NOT silently weaken end-to-end policy.

## 4. Service boundaries

### 4.1 Gateway

Owns:

- API authentication;
- request validation;
- rate limiting;
- policy parsing;
- model lookup;
- streaming response framing;
- request cancellation.

Does not own:

- final placement;
- provider settlement;
- model artifact storage.

### 4.2 Job orchestrator

The initial repository did not name a separate orchestrator, but the responsibilities are distinct enough to model explicitly.

Owns:

- canonical job lifecycle;
- planning request to scheduler;
- capacity reservation workflow;
- dispatch;
- cancellation;
- replan/retry coordination;
- completion/verification transition.

It MAY begin inside the scheduler service for M1, but the boundary MUST remain explicit in code.

### 4.3 Scheduler and topology engine

Owns:

- feasibility filtering;
- predicted performance model;
- placement generation;
- topology classification;
- reservation candidates;
- replan candidates;
- placement explanation.

The scheduler does not trust static GPU model names as sufficient performance information.

### 4.4 Registry

Owns:

- model versions;
- model license metadata;
- runtime compatibility;
- partition strategies;
- shard manifests;
- artifact digests;
- signatures;
- artifact availability.

### 4.5 Verification

Owns:

- risk classification;
- canary scheduling;
- sampled redundancy;
- trace/challenge evaluation;
- verification outcomes;
- trust/reputation inputs.

It MUST NOT claim cryptographic proof of correct inference unless such a mechanism is actually implemented and independently evaluated.

### 4.6 Billing

Owns:

- immutable metering inputs;
- job charge computation;
- provider earnings;
- refunds/credits;
- settlement batches;
- ledger invariants.

### 4.7 Telemetry

Owns:

- event ingestion;
- metrics;
- traces;
- network observations;
- provider availability history;
- benchmark history;
- operational dashboards.

Telemetry is not the source of truth for monetary balances.

## 5. Control plane versus data plane

### Control plane

Low-bandwidth, reliability-oriented operations:

- enrollment;
- authentication;
- node profile updates;
- benchmark results;
- topology measurements;
- model metadata;
- planning;
- reservations;
- job commands;
- lifecycle transitions;
- verification metadata;
- billing events.

### Data plane

Latency/throughput-sensitive operations:

- model artifact transfer;
- stage activation transfer;
- selected runtime control frames;
- token/result streaming;
- optional KV migration for recovery/rebalance;
- verification traces where required.

A dedicated data-plane connection MAY be peer-to-peer, relayed, or service-mediated depending on policy and network reachability.

## 6. Inference execution model

### 6.1 Prefill and decode are different

The scheduler MUST model prefill and decode separately.

**Prefill** tends to have:

- large input sequence work;
- high parallel compute opportunity;
- large temporary activation demand;
- latency that may tolerate batching depending on workload.

**Decode** tends to have:

- small per-token compute units;
- sequential token dependency;
- strong sensitivity to per-stage latency;
- persistent KV-cache growth.

A placement that is good for prefill may be bad for decode.

### 6.2 Pipeline parallel path

For a dense transformer split by contiguous layers:

```text
tokens
  |
  v
Stage 0 -> activation -> Stage 1 -> activation -> ... -> Stage N -> logits
```

Each stage owns its layers and normally owns the KV cache for those layers. Moving the entire KV cache on every token would be unnecessarily expensive. KV transfer is instead expected for:

- migration;
- failover;
- context handoff;
- explicit rebalancing;
- checkpoint/restore experiments.

### 6.3 Tensor parallelism

Tensor parallelism requires frequent collectives and SHOULD be restricted to links whose measured latency and bandwidth make the selected runtime viable. It is primarily an intra-host or tightly-coupled cluster strategy, not a generic WAN strategy.

### 6.4 Expert parallelism / MoE

MoE allows conditional expert activation, which may make network-aware placement attractive. However, routing still creates activation traffic, tail-latency sensitivity, and expert-capacity imbalance. ComputeMesh MUST measure these effects rather than assume MoE solves WAN cost.

### 6.5 Data parallelism

Independent model replicas can serve separate requests or batches. This is the easiest mode to distribute broadly but does not combine memory to fit a single oversized model request.

## 7. Scheduling model

### 7.1 Phase A — hard feasibility constraints

A candidate node or route is rejected if any mandatory condition fails:

- model/runtime compatibility;
- sufficient memory with safety margin;
- supported quantization;
- architecture/device capability;
- provider policy;
- privacy tier;
- region requirement;
- license restriction;
- trust minimum;
- version compatibility;
- deadline impossibility;
- price ceiling;
- thermal/power restriction;
- artifact availability or acceptable fetch time.

### 7.2 Phase B — predicted plan evaluation

For feasible plans, estimate:

- prefill time;
- decode time/token;
- stage transfer time;
- queue/reservation delay;
- artifact preparation delay;
- expected failure/recovery penalty;
- verification overhead;
- monetary cost;
- confidence interval / prediction uncertainty.

### 7.3 Phase C — objective selection

The scheduler should solve a multi-objective problem rather than use one permanent hand-written ratio.

A plan may optimize a weighted objective such as:

```text
objective =
    w_latency   * predicted_latency
  + w_cost      * predicted_cost
  + w_failure   * expected_failure_penalty
  + w_variance  * prediction_uncertainty
```

subject to hard constraints.

Weights derive from the request policy: interactive, cheapest, deadline-bound, private, high-reliability, batch, etc.

### 7.4 Placement explanation

For every planned job, store:

- accepted constraints;
- rejected candidates and primary reason;
- predicted latency/cost;
- selected execution mode;
- selected model/shard versions;
- expected network path;
- verification policy;
- fallback/replan plan.

This is essential for debugging, support, economics, and trust.

## 8. Capacity reservation

Scheduling without reservation creates a race between planning and dispatch.

Required abstraction:

```text
DISCOVERED -> CANDIDATE -> LEASED -> COMMITTED -> ACTIVE -> RELEASED
```

A reservation has:

- `reservation_id`;
- `node_id`;
- resource set;
- model/stage;
- memory budget;
- start deadline;
- lease expiration;
- price terms;
- job binding;
- monotonic revision.

Expired leases MUST release capacity automatically.

## 9. Node architecture

A provider node should contain:

```text
+--------------------------------------------------+
| Node Agent                                       |
|--------------------------------------------------|
| identity / enrollment                            |
| update + signature verification                  |
| hardware discovery                               |
| benchmark runner                                 |
| availability + policy                            |
| reservation manager                              |
| artifact cache                                   |
| worker supervisor                                |
| telemetry exporter                               |
| drain / shutdown                                 |
+----------------------+---------------------------+
                       |
                  constrained IPC
                       |
+----------------------v---------------------------+
| Runtime Worker(s)                                |
| model-specific, signed, resource-constrained     |
+----------------------+---------------------------+
                       |
                    GPU/CPU
```

The agent MUST NOT expose a generic remote-execution API.

## 10. Model artifacts

### 10.1 Model manifest

A model version must declare at least:

- canonical model ID/version;
- source and license metadata;
- architecture;
- tokenizer/config digests;
- supported runtimes;
- quantizations;
- partitionable boundaries;
- memory model;
- compatibility constraints;
- expected shard set;
- safety/privacy metadata where applicable.

### 10.2 Shard manifest

A shard must declare:

- immutable digest;
- model version;
- byte size;
- tensor/layer/expert range;
- quantization;
- runtime compatibility;
- expected device memory;
- artifact signature metadata.

The registry should reference artifacts by digest. Human-friendly names are aliases, not identity.

## 11. Topology and network measurements

Do not hard-code network quality from labels such as LAN/WAN alone.

Each relevant path should track:

- round-trip latency distribution;
- one-way latency if safely measurable;
- available throughput;
- jitter;
- packet loss;
- retransmission indicators;
- connection setup cost;
- observed application transfer throughput;
- measurement timestamp;
- confidence/freshness.

Network classes MAY be derived from measurements for convenience, but raw observations remain available.

## 12. State and consistency

### 12.1 Source-of-truth principles

- PostgreSQL is the planned durable control-plane source of truth.
- Financial ledger entries are append-only.
- Verification outcomes are immutable; corrections are new records.
- Job state transitions use optimistic concurrency or equivalent revision checks.
- Telemetry/event streams may be eventually consistent.
- Monetary settlement never depends solely on eventually consistent dashboards.

### 12.2 Idempotency

Every externally retryable state mutation uses a stable `request_id` / idempotency key. The receiver stores the result long enough that duplicates can return the original outcome.

## 13. Failure model

Expected failures include:

- provider process crash;
- provider disconnect;
- GPU reset/OOM;
- artifact corruption;
- runtime incompatibility;
- reservation expiry;
- route degradation;
- scheduler restart;
- database failover;
- duplicate messages;
- stale commands;
- malicious or incorrect results.

Recovery policy depends on the stage.

Examples:

- before execution: replan with no billable work;
- during prefill: retry/replan from a defined checkpoint or restart;
- during decode: replace affected stage only if state can be reconstructed safely; otherwise restart from last safe checkpoint;
- ambiguous completion: do not settle until reconciled.

See `docs/FAILURE_SEMANTICS.md`.

## 14. Verification model

Verification is probabilistic and risk-based in V1.

Potential signals:

- signed worker version;
- benchmark consistency;
- canary workload;
- sampled duplicate execution;
- trace consistency;
- runtime health;
- node reputation;
- observed performance versus claim.

A trusted history reduces risk but does not make a provider cryptographically trustworthy.

## 15. Privacy model

Privacy is determined by what plaintext or model state a provider can access.

At minimum:

- `public_compute`: assume provider-controlled host can inspect process memory/traffic terminating there;
- `region_verified`: geographic/operational constraints, not confidentiality by itself;
- `datacenter_only`: provider class constraint, not automatically confidential;
- `confidential_compute`: only valid when backed by a defined confidential-computing mechanism and attestation policy.

Never advertise encrypted transport as equivalent to confidential execution.

See `docs/PRIVACY_TIERS.md`.

## 16. Observability

Every job should reconstruct:

- request/job ID;
- model/runtime version;
- placement revision;
- reservation IDs;
- participating nodes;
- stage boundaries;
- preparation time;
- prefill timing;
- per-token decode timing distributions;
- bytes transferred by stream class;
- retry/replan events;
- verification outcome;
- billable units;
- final charge and provider allocations.

Prompt/output bodies are excluded from default telemetry.

## 17. Scale strategy

M1 should optimize for correctness and measurements, not microservice count. Several logical services MAY initially share one deployable.

Scale boundaries should be split only when justified by:

- independent security boundary;
- throughput need;
- failure isolation;
- deployment ownership;
- data ownership.

## 18. Initial ADR backlog

Required before M1 implementation is considered architecture-complete:

- runtime baseline;
- control/data serialization;
- M1 transport stack;
- node identity and key lifecycle;
- model/shard manifest format;
- reservation semantics;
- telemetry envelope;
- ledger precision and units;
- artifact signature scheme;
- first privacy-tier enforcement model.
