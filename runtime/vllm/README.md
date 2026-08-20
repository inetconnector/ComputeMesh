# vLLM Runtime Integration

**Status:** planned component

## Purpose

Evaluate vLLM as a reference/runtime option for coordinated multi-GPU and multi-node serving, especially datacenter-style capacity.

## Responsibilities

- vLLM adapter experiments
- parallelism mapping
- metrics integration
- compatibility notes

## Non-goals

- assuming vLLM's cluster model maps directly to unreliable consumer WAN nodes

## Canonical interfaces

- registry
- scheduler
- node/datacenter worker

## M1 scope

- comparison baseline rather than mandatory first path unless ADR selects it

## Required tests / evidence

- model load
- TP/PP configuration
- failure behavior
- environment consistency

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
