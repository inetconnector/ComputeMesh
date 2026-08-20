# Protocol Package

**Status:** planned component

## Purpose

Machine-readable protocol schemas, generated clients, compatibility tests, and examples.

## Responsibilities

- control message schemas
- manifest schemas if colocated
- error codes
- version negotiation fixtures
- generated client code

## Non-goals

- hand-maintained generated code
- transport-specific business semantics

## Canonical interfaces

- `PROTOCOL.md` as human-readable canonical specification

## M1 scope

- schema for hello/profile/reservation/job/failure

## Required tests / evidence

- round-trip
- unknown fields
- version compatibility
- malformed input
- size limits

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
