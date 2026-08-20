# llama.cpp Runtime Integration

**Status:** planned component

## Purpose

Research adapter for llama.cpp-family local/remote execution capabilities.

## Responsibilities

- runtime adapter experiments
- model loading/partition mapping
- instrumentation
- failure/cancellation mapping

## Non-goals

- exposing upstream experimental RPC directly to the public internet
- treating upstream RPC authentication/security as ComputeMesh security

## Canonical interfaces

- node worker
- registry manifests
- runtime network layer

## M1 scope

- two-node spike with controlled stage/remote execution if viable
- record upstream version

## Required tests / evidence

- correctness
- version compatibility
- disconnect
- cache/load timing
- security boundary

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
