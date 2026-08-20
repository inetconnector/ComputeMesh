# Scheduler and Topology Service

**Status:** planned component

## Purpose

Generate explainable feasible placements from model, resource, network, trust, and policy inputs.

## Responsibilities

- hard feasibility filtering
- candidate generation
- latency/cost/failure prediction
- topology observations
- placement ranking
- fallback candidates
- placement explanation

## Non-goals

- executing runtime work
- silently relaxing privacy/budget constraints
- treating a static GPU model name as sufficient performance evidence

## Canonical interfaces

- node profiles
- benchmark store
- registry
- reservation/orchestrator
- verification policy

## M1 scope

- two-node feasibility
- memory-aware contiguous-layer placement
- simple predicted transfer/compute model
- explanation

## Required tests / evidence

- hard constraints
- determinism
- prediction bookkeeping
- stale profile rejection
- no feasible plan

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
