# Telemetry Service

**Status:** planned component

## Purpose

Collect privacy-minimized operational evidence for performance, reliability, and debugging.

## Responsibilities

- metrics ingestion
- structured events
- traces
- network observations
- benchmark history
- availability history
- dashboards/alerts

## Non-goals

- raw prompt/output logging by default
- authoritative financial balances
- unbounded crash dumps

## Canonical interfaces

- all services/node exporters
- scheduler feature store/read model
- operations

## M1 scope

- job phase timings
- stage compute/transfer
- node health
- network measurements

## Required tests / evidence

- duplicate events
- schema version
- redaction/privacy lint
- cardinality bounds

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
