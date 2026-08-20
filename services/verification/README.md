# Verification and Reputation Service

**Status:** planned component

## Purpose

Attach risk-based verification policy to jobs and maintain evidence-backed trust signals.

## Responsibilities

- risk classification
- canaries
- sampled redundancy
- trace/challenge rules
- verification results
- reputation evidence/aggregation

## Non-goals

- claiming cryptographic proof without one
- making confidentiality guarantees
- overriding scheduler hard privacy constraints

## Canonical interfaces

- scheduler
- orchestrator
- billing
- telemetry

## M1 scope

- verification policy schema
- canary hook
- result record
- new-node probation

## Required tests / evidence

- policy selection
- duplicate result
- disagreement
- reputation decay/confidence

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
