# Gateway Service

**Status:** planned component

## Purpose

Public API entry point and compatibility layer.

## Responsibilities

- API authentication
- request schema validation
- rate/budget enforcement at edge
- OpenAI-compatible framing
- ComputeMesh namespaced policy parsing
- streaming/cancellation
- request IDs

## Non-goals

- placement decisions
- provider selection
- ledger mutation outside defined billing API

## Canonical interfaces

- Job orchestrator
- model catalog/read API
- identity/auth
- public SDK

## M1 scope

- create one chat/responses job
- stream lifecycle/result
- cancel

## Required tests / evidence

- auth
- rate limit
- schema fuzz
- oversized input
- idempotent job create
- disconnect/cancel

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
