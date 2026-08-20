# Billing and Ledger Service

**Status:** planned component

## Purpose

Convert accepted metering evidence into auditable customer charges and provider balances.

## Responsibilities

- pricing evaluation
- metering acceptance
- append-only double-entry ledger
- refund/credit events
- provider balance
- settlement aggregation
- reconciliation

## Non-goals

- using floating point for money
- trusting arbitrary provider invoices
- editing posted ledger rows in place

## Canonical interfaces

- orchestrator/metering
- verification
- payment provider
- dashboard read model

## M1 scope

- simulation only until execution evidence stabilizes
- define units and invariants

## Required tests / evidence

- debit=credit
- duplicate event
- refund bounds
- rounding
- reconciliation

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
