# ComputeMesh SDK

**Status:** planned component

## Purpose

Client libraries over the public Gateway API.

## Responsibilities

- API convenience
- stream handling
- ComputeMesh policy types
- retry rules safe for public endpoints

## Non-goals

- direct node control
- scheduler APIs
- provider secrets

## Canonical interfaces

- Gateway API

## M1 scope

- defer until public API skeleton stabilizes

## Required tests / evidence

- compatibility
- stream cancellation
- API errors

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
