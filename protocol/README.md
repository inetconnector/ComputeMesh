# Protocol Package

**Status:** M0 control envelope, durable initial handlers, authentication-gated node-session semantics, and the first strict node-session wire binding are implemented; no production credential verifier or network transport binding exists yet.

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

The durable orchestration payload contracts deliberately remain limited to operations already implemented in `services/orchestrator/handlers.py`:

- `ReserveCapacity`;
- `CommitReservation`;
- `CancelJob`.

Those handlers bind envelope `request_id` to durable SQLite state effects. Message type + payload are fingerprinted so exact replays have one business effect and changed-payload request-ID reuse is rejected.

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
- a supplied control-envelope `actor_id` can be bound to the verifier-confirmed node ID before authentication advances;
- protocol-major mismatch is rejected and the current M0 minor version is negotiated down from a higher compatible peer minor;
- credentials are rechecked for expiry before later session progress;
- capability negotiation is intersection-based and required capabilities cannot be silently dropped;
- profile revision must match accepted benchmark status before `READY`;
- drain is only valid from `READY`;
- an external revocation/incident signal can terminate the session.

This module defines **session semantics and a verifier boundary only**. It does not select Ed25519, X.509, JWT, mTLS, TPM/TEE attestation, or another credential mechanism. It also does not implement enrollment, issuance, key storage, rotation, or revocation lookup. ADR 0005 remains Proposed.

## Initial node-session wire binding

`session_contracts.py` and `session_wire.py` now bind an already parsed `ControlEnvelope` to the semantic session for the documented M0 readiness subset:

- `NodeHello`;
- `NodeAuthenticate`;
- `CapabilityNegotiation`;
- `NodeProfileUpdate`;
- `BenchmarkReport`;
- `DrainRequest`.

The binding is intentionally narrow and strict:

- `NodeHello` carries protocol major/minor, agent/platform data, optional stable node ID, advertised auth methods, and capabilities;
- the `NodeHello` payload version must match its envelope, then the session records the negotiated version;
- `NodeAuthenticate` carries only a bounded opaque credential + advertised method; credential interpretation remains entirely inside the injected verifier;
- successful authentication must bind envelope `actor_id` to the verifier-confirmed node ID before state advances;
- every later session message requires that authenticated `actor_id`;
- `expected_revision` is checked against the session revision before a first-time message is applied;
- successful `request_id` effects are session-locally fingerprinted: an exact replay returns the original snapshot, while semantic request-ID reuse is rejected;
- `CapabilityNegotiation` can accept only capabilities present in both the node advertisement and the configured control-plane set, and configured required capabilities remain mandatory;
- `NodeProfileUpdate` reuses the complete `node_profile.schema.json` contract and its `node_id` must equal the authenticated node;
- `BenchmarkReport` reuses `benchmark_result.schema.json` and must match the synced profile revision;
- benchmark readiness is decided by an injected `BenchmarkAcceptancePolicy`; there is deliberately no accept-all default, and policy may require several accepted reports before returning `READY`;
- `DrainRequest` binds the documented reason to the existing `READY -> DRAINING` transition.

This is **not a network service**. A transport/router must first parse and validate the common envelope and route it to the correct session. Authorization beyond the authenticated node-actor binding, rate/resource limits, persistence of session state, and production transport security remain separate responsibilities.

## Test

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s protocol/tests -v
```

Latest combined local protocol verification: **53/53 passing**. This includes the existing envelope/durable-message/schema tests, 17 node-session semantic tests, 6 session-contract tests, and 15 wire-binding tests. The new negative coverage includes protocol-version mismatch, actor mismatch, stale session revision, request-ID semantic reuse, unoffered capabilities, profile/node mismatch, stale benchmark revision, rejected benchmark readiness, and invalid session-message families.

Relevant Python modules also pass `py_compile`.

## Remaining work

- choose and implement the concrete ADR-0005 node identity, enrollment, credential, rotation, and revocation path;
- add authorization policy beyond authenticated node-actor binding;
- select and implement the control/data transport under ADR 0003;
- bind remaining availability/reservation/job/artifact/runtime/result/failure/heartbeat operations required by M1;
- decide which session state/evidence must become durable when the real network service is introduced;
- add protocol fuzz/property coverage before production exposure.

## Security boundary

A syntactically valid `actor_id` is not trusted identity. A successful test `FakeVerifier` is not production authentication. The new wire binder only ensures that, **if** an injected verifier authenticates a node, subsequent session messages cannot silently claim another actor or bypass session revision/readiness ordering. Network exposure remains blocked until a real verifier, authorization layer, rate/resource limits, and transport security are selected, implemented, and reviewed.
