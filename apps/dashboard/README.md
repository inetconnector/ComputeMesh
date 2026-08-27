# ComputeMesh Dashboard

**Status:** dedicated account dashboard application planned. Existing public portal and NodeOS/appliance dashboards are separate surfaces and do not make `apps/dashboard` complete.

## Purpose

Web visibility for customers, providers, and operators with role-specific access.

## Current boundary

ComputeMesh already contains public portal/status pages and an appliance/provider dashboard surface, while gateway/billing APIs expose some of the data a future account dashboard would consume. A production multi-user `apps/dashboard` with account RBAC, job history and cross-tenant isolation is **not** implemented yet.

No current dashboard/portal should present unavailable global capacity or production-readiness metrics as measured facts unless an authenticated source supplies them.

## Responsibilities

- job history
- usage/cost display
- provider fleet summary
- capacity/model availability
- verification/reliability summaries
- account settings

## Non-goals

- source of truth for ledger
- direct unsafeguarded runtime control
- displaying raw prompts in operational views by default
- exposing private ranking/reputation/fraud/pricing internals

## Canonical interfaces

- Gateway/read APIs
- billing read model
- future telemetry aggregates
- bounded public/provider status models

## First production scope

- authenticated job list/detail
- balance/usage read view
- provider status for the authenticated provider
- pagination and explicit unavailable/unknown states

## Required tests / evidence

- RBAC
- cross-account data isolation
- large history pagination
- redacted telemetry
- unavailable/stale metric handling
- no fabricated global capacity/performance values

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

See `docs/CURRENT_STATUS.md` for current system status. Update this file when a real `apps/dashboard` application is implemented.
