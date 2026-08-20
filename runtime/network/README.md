# Runtime Network Layer

**Status:** planned component

## Purpose

Transport-neutral application layer for artifact, activation, result, KV-migration, and verification streams.

## Responsibilities

- stream framing
- backpressure
- chunking
- integrity binding
- connection metrics
- transport adapters

## Non-goals

- job business state
- provider authorization policy
- arbitrary generic RPC

## Canonical interfaces

- `PROTOCOL.md`
- runtime adapters
- node agent

## M1 scope

- activation microbenchmark over at least two candidate stacks
- bounded queue

## Required tests / evidence

- jitter/loss
- reconnect
- oversized frame
- backpressure
- stale placement

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
