# ComputeMesh Admin

**Status:** dedicated admin application planned. Existing admin-capable gateway endpoints and operator tooling are foundations, not this application.

## Purpose

Restricted operations interface for incident handling and exceptional administrative workflows.

## Current boundary

The public gateway already exposes selected authenticated admin operations (for example provider/settlement read or execution paths where configured), and the repositories contain operator/diagnostic tooling. There is **no dedicated production `apps/admin` UI/service** yet, so those existing capabilities must not be mistaken for a completed admin application.

Private control-plane score traces, fraud/reputation internals, pricing policy and private operational databases must not be surfaced by a future admin UI except through explicitly authorized operator-only views.

## Responsibilities

- node review/quarantine
- incident workflow
- audited reputation/fraud intervention where policy permits
- billing/settlement investigation views
- registry operations
- release/launch readiness

## Non-goals

- silent mutation of ledger
- unaudited trust overrides
- routine customer/provider UX
- exposing private policy/data to public users

## Canonical interfaces

- admin-only service APIs
- audit log
- registry
- verification/private trust services through authorized backend interfaces
- billing/settlement

## First production scope

- authenticated operator RBAC
- read-only incident/provider/job views first
- explicit reason/audit trail for mutations
- no direct raw database editing

## Required tests / evidence

- least privilege/RBAC
- cross-tenant isolation
- break-glass audit
- override reason required
- no direct ledger rewrite
- redaction of secrets/private score internals by default

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

See `docs/CURRENT_STATUS.md` for current system status. Update this file when a real `apps/admin` entry point is implemented.
