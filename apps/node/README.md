# ComputeMesh Provider Node

**Status:** provider application remains planned; shared M0 node-session semantics now exist in `protocol/node_session.py`.

## Purpose

Windows-first provider agent and local provider experience.

## Responsibilities

- node enrollment and local identity integration;
- hardware/runtime discovery;
- benchmark execution and profile publication;
- availability, power, thermal, and sharing policy;
- capacity reservation handling;
- artifact cache orchestration;
- signed runtime-worker supervision;
- telemetry export;
- safe drain, update, rollback, diagnostics, and uninstall.

## Current shared foundation

The provider application itself is not implemented, but the transport-neutral session lifecycle it must obey is now modeled in `protocol/node_session.py`:

```text
CONNECTED -> HELLO_RECEIVED -> AUTHENTICATED
-> CAPABILITIES_NEGOTIATED -> PROFILE_SYNCED -> READY
-> DRAINING -> CLOSED
```

The session layer requires an injected `AuthenticationVerifier` and has no permissive default. It checks credential expiry, advertised/authenticated node-ID consistency, capability negotiation, profile/benchmark revision consistency, and drain ordering.

This does **not** mean production node authentication exists. The concrete credential format, key algorithm, enrollment/issuer flow, OS-protected private-key integration, rotation, revocation backend, and network binding remain open under ADR 0005.

## Non-goals

- arbitrary remote shell or customer code execution;
- global scheduling decisions;
- financial ledger authority;
- trusting provider self-reported performance without server observation;
- treating signed software or a valid node credential as proof the host is uncompromised.

## Canonical interfaces

- `PROTOCOL.md` node control messages;
- `protocol/node_session.py` M0 session semantics;
- `docs/adr/0005-node-identity.md` proposed identity/key lifecycle;
- `docs/BENCHMARK_SPEC.md` benchmark records;
- `docs/FAILURE_SEMANTICS.md` node/reservation/job failure behavior;
- `THREAT_MODEL.md` provider-host boundary.

## M1 scope

- enroll two nodes;
- establish authenticated sessions using the eventually selected ADR-0005 mechanism;
- publish versioned profile;
- run benchmark subset;
- accept short reservation lease;
- prepare verified artifact;
- start one constrained runtime stage;
- drain safely.

## Required tests / evidence

- successful enrollment/authentication;
- expired/revoked credential behavior;
- reboot/reconnect;
- duplicate/stale command;
- reservation expiry;
- OOM/runtime crash;
- cache digest mismatch;
- drain during/around work;
- update rollback.

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors/metrics without raw prompt/output content.
- Never provide a permissive authentication fallback.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production provider-node executable, installer, enrollment client, runtime supervisor, or network session binding exists yet. The current implementation is only a shared protocol/session semantic foundation.
