# ComputeMesh Desktop

**Status:** dedicated end-user desktop client planned. Existing Windows/provider installers and node applications are separate provider/operations surfaces.

## Purpose

End-user desktop surface for model execution plus optional provider controls where the same machine also shares compute.

## Current boundary

The repository has Windows/provider application and installer work plus public Gateway APIs, but there is no completed `apps/desktop` customer client implementing the UX below. Provider-node setup must not be presented as this end-user desktop application.

## Responsibilities

- authentication UX
- model selection
- policy/budget/privacy controls
- job progress and streaming
- provider status shortcut when locally installed
- diagnostics/support export

## Non-goals

- manual shard placement
- exposing provider identities by default
- claiming confidentiality not provided by the selected privacy tier
- embedding private scheduler/reputation/pricing logic

## Canonical interfaces

- Gateway public API
- job status/cancellation API
- provider-node local API when installed

## First production scope

- connect to gateway
- submit one supported request
- show planning/preparing/running phases
- stream result when the production runtime supports true upstream streaming
- cancel job
- display explicit unavailable/degraded states

## Required tests / evidence

- offline gateway
- unsupported privacy tier
- budget rejection
- cancellation
- partial stream failure
- credential storage
- update/rollback behavior

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

See `docs/CURRENT_STATUS.md` for current system status. Update this file when a real `apps/desktop` customer entry point is implemented.
