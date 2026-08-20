# ComputeMesh Documentation Review — 2026-08-20

## Scope

Reviewed the documentation present in the initial repository bootstrap:

- root project documents;
- architecture/protocol/security documents;
- state handoff;
- ADRs;
- all component directory READMEs.

## Main findings

### 1. Vision and implementation contract were mixed

The bootstrap documents correctly described the intended system, but many statements did not distinguish:

- fixed invariant;
- hypothesis;
- proposed design;
- accepted decision;
- measured fact.

The v0.2 rewrite labels these more explicitly.

### 2. Scheduler model was too simplistic

The original illustrative score:

```text
(compute * reliability * locality * availability) / (latency * price * failure_risk)
```

is useful as intuition but unsafe as the scheduling architecture.

The revised model uses:

1. hard feasibility constraints;
2. prediction of latency/cost/failure;
3. request-policy-weighted objective;
4. placement explanation.

### 3. Reservation semantics were missing

A distributed scheduler needs a lease between placement and dispatch. Without it, capacity can disappear or be double-assigned.

The architecture now introduces reservation states and expiry.

### 4. Prefill and decode were not separated enough

They have different bottlenecks and must be benchmarked and scheduled separately.

### 5. KV-cache transport needed clarification

KV cache should normally remain with the layers/stage that owns it. Constant WAN KV transfer would be expensive. The docs now treat KV transfer as migration/recovery/rebalance unless a runtime explicitly requires another design.

### 6. Protocol was an outline, not a specification

Missing elements included:

- protocol version negotiation;
- common envelope;
- idempotency semantics;
- errors;
- deadlines;
- leases;
- backpressure;
- stream classes;
- cancellation;
- replay protection.

These are now specified at draft level.

### 7. Privacy claims needed stronger limits

Encrypted transport does not make provider execution confidential. The new privacy-tier spec makes `confidential_compute` unavailable as a guarantee until a concrete attestation/TEE design exists.

### 8. Verification needed residual-risk language

Canaries, redundancy, and reputation can lower error/fraud risk but are not automatically cryptographic proof of inference.

### 9. Data model was too coarse

The revised model separates:

- node versus node profile;
- job versus placement versus attempt;
- metering versus ledger;
- model versus immutable model version versus artifact/shard;
- reservation versus availability.

### 10. Failure/billing semantics needed one canonical document

The new failure spec defines retries, replans, stale results, reservation expiry, ambiguous completion, cancellation, and billing neutrality.

## New documents added

- `docs/BENCHMARK_SPEC.md`
- `docs/DATA_MODEL.md`
- `docs/FAILURE_SEMANTICS.md`
- `docs/PRIVACY_TIERS.md`
- `docs/TEST_MATRIX.md`
- `research/TECHNOLOGY_BASELINE.md`
- ADRs 0002-0007

## Recommended next engineering action

Do not create the marketplace layer next.

The highest-value next sequence is:

```text
runtime ADR
-> node/profile schemas
-> benchmark harness
-> reservation/job state skeleton
-> local runtime baseline
-> two-node transport benchmark
-> shared inference
```

That sequence gives the scheduler real data and attacks the core feasibility risk first.
