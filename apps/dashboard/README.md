# ComputeMesh Dashboard

**Status:** planned component

## Purpose

Web visibility for customers, providers, and operators with role-specific access.

## Responsibilities

- job history
- usage/cost display
- provider fleet summary
- capacity/model availability
- verification/reliability summaries
- account settings

## Non-goals

- source of truth for ledger
- direct runtime control
- displaying raw prompts in operational views by default

## Canonical interfaces

- Gateway/read APIs
- billing read model
- telemetry aggregates

## M1 scope

- minimal job list/detail after API exists

## Required tests / evidence

- RBAC
- cross-account data isolation
- large history pagination
- redacted telemetry

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
