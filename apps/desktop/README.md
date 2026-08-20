# ComputeMesh Desktop

**Status:** planned component

## Purpose

End-user desktop surface for model execution plus optional provider controls where the machine also shares compute.

## Responsibilities

- authentication UX
- model selection
- policy/budget/privacy controls
- job progress and streaming
- provider status shortcut
- diagnostics/support export

## Non-goals

- manual shard placement
- exposing provider identities by default
- claiming confidentiality not provided by selected privacy tier

## Canonical interfaces

- Gateway public API
- job status API
- provider-node local API when installed

## M1 scope

- connect to gateway
- submit one supported request
- show planning/preparing/running phases
- stream result
- cancel job

## Required tests / evidence

- offline gateway
- unsupported privacy tier
- budget rejection
- cancellation
- partial stream failure

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
