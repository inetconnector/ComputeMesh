# ComputeMesh Provider Node

**Status:** planned component

## Purpose

Windows-first provider agent and local provider experience.

## Responsibilities

- node enrollment and local identity integration
- hardware/runtime discovery
- benchmark execution and profile publication
- availability, power, thermal, and sharing policy
- capacity reservation handling
- artifact cache orchestration
- signed runtime-worker supervision
- telemetry export
- safe drain, update, rollback, diagnostics, and uninstall

## Non-goals

- arbitrary remote shell or customer code execution
- global scheduling decisions
- financial ledger authority
- trusting provider self-reported performance without server observation

## Canonical interfaces

- `PROTOCOL.md` node control messages
- `docs/BENCHMARK_SPEC.md` benchmark records
- `docs/FAILURE_SEMANTICS.md` node/reservation/job failure behavior
- `THREAT_MODEL.md` provider-host boundary

## M1 scope

- enroll two nodes
- publish versioned profile
- run benchmark subset
- accept short reservation lease
- prepare verified artifact
- start one constrained runtime stage
- drain safely

## Required tests / evidence

- reboot/reconnect
- duplicate command
- stale assignment
- reservation expiry
- OOM/runtime crash
- cache digest mismatch
- drain during job
- update rollback

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
