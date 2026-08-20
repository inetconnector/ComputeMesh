# ComputeMesh Tests

**Status:** planned component

## Purpose

Cross-component test harnesses and reproducible distributed/chaos scenarios.

## Responsibilities

- integration fixtures
- distributed lab tests
- chaos tests
- performance harness integration
- billing/security scenarios

## Non-goals

- hiding component unit tests that belong near code

## Canonical interfaces

- `docs/TEST_MATRIX.md`
- `docs/BENCHMARK_SPEC.md`

## M1 scope

- two-node end-to-end test
- duplicate command
- node loss
- artifact corruption

## Required tests / evidence

- this directory is itself the system-test layer

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
