# Protocol Package

**Status:** M0 control envelope, initial documented message handlers, and authentication-gated node-session semantics implemented; no production credential verifier or network transport binding yet.

## Purpose

Provide machine-readable protocol contracts, transport-neutral control semantics, compatibility checks, structured errors, and session readiness rules without prematurely coupling the design to a transport or cryptographic implementation.

## Common control envelope

`control.py`:

- parses the common envelope from `PROTOCOL.md`;
- rejects unknown/missing security-sensitive base fields;
- enforces protocol-major compatibility;
- validates identifiers, revision shape, RFC3339 timestamps, expiry, and bounded clock skew;
- emits structured machine-readable errors;
- does not authenticate or authorize actors.

## Initial message payload contracts and durable handlers

The first implemented payload contracts deliberately cover only operations already named by `PROTOCOL.md`:

- `ReserveCapacity`;
- `CommitReservation`;
- `CancelJob`.

The corresponding application handlers live in `services/orchestrator/handlers.py` and bind envelope `request_id` to durable state effects. Message type + payload are fingerprinted so exact replays have one effect and changed-payload request-ID reuse is rejected.

## Node-session semantic skeleton

`node_session.py` implements the protocol-level readiness sequence:

```text
CONNECTED
 -> HELLO_RECEIVED
 -> AUTHENTICATED
 -> CAPABILITIES_NEGOTIATED
 -> PROFILE_SYNCED
 -> READY
 -> DRAINING
 -> CLOSED
```

Key properties:

- no built-in permissive authenticator exists;
- callers must inject an `AuthenticationVerifier`;
- the verifier receives session ID and a per-session challenge so the eventual proof mechanism can bind credentials to the session;
- successful authentication requires stable node ID, provider principal, and a future credential expiry;
- an advertised stable node ID must match the authenticated node ID;
- credentials are rechecked for expiry before later session progress;
- capability negotiation is intersection-based and required capabilities cannot be silently dropped;
- profile revision must match accepted benchmark status before `READY`;
- drain is only valid from `READY`;
- an external revocation/incident signal can terminate the session.

This module defines **session semantics and a verifier boundary only**. It does not select Ed25519, X.509, JWT, mTLS, TPM/TEE attestation, or another credential mechanism. It also does not implement enrollment, issuance, key storage, rotation, or revocation lookup. ADR 0005 remains Proposed.

## Test

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s protocol/tests -v
```

Latest combined local protocol verification: **29/29 passing**. The node-session portion adds 14 tests covering authentication gating, expiry, node-ID matching, capability mismatch, profile/benchmark consistency, drain order, and external termination.

## Remaining work

- choose/implement the concrete ADR-0005 identity and credential path;
- define wire payload contracts for NodeHello, NodeAuthenticate, CapabilityNegotiation, ProfileSync, BenchmarkStatus, and DrainRequest;
- bind those wire messages to the semantic session state machine;
- add authorization policy after authenticated identity is available;
- select the control/data transport under ADR 0003;
- add remaining artifact/runtime/result/heartbeat protocol operations required by M1.

## Security boundary

A syntactically valid `actor_id` is not trusted identity. A successful test `FakeVerifier` is not production authentication. Network exposure remains blocked until a real verifier, authorization layer, rate/resource limits, and transport security are selected and reviewed.
