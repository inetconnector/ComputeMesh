# Protocol Package

**Status:** M0 control envelope, durable initial handlers, node-session semantics/wire binding, and an M1 Ed25519 reference verifier are implemented. There is still no production network transport or production identity service.

## Purpose

Provide machine-readable protocol contracts, transport-neutral control semantics, compatibility checks, structured errors, session readiness rules, and a narrow reference node-authentication mechanism without coupling the public protocol to one transport.

## Common control envelope

`control.py`:

- parses the common envelope from `PROTOCOL.md`;
- rejects unknown/missing security-sensitive base fields;
- enforces protocol-major compatibility;
- validates identifiers, revision shape, RFC3339 timestamps, expiry, and bounded clock skew;
- emits structured machine-readable errors;
- does not by itself authenticate or authorize actors.

## Durable orchestration messages

The durable orchestration payload contracts remain limited to operations implemented in `services/orchestrator/handlers.py`:

- `ReserveCapacity`;
- `CommitReservation`;
- `CancelJob`.

Those handlers bind envelope `request_id` to durable SQLite state effects. Exact replay has one business effect; changed semantic reuse of the same request ID is rejected.

## Node-session semantics and wire binding

`node_session.py`, `session_contracts.py`, and `session_wire.py` implement the initial readiness path:

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

The current wire subset is:

- `NodeHello`;
- `NodeAuthenticate`;
- `CapabilityNegotiation`;
- `NodeProfileUpdate`;
- `BenchmarkReport`;
- `DrainRequest`.

Key properties:

- there is no permissive authenticator;
- callers must inject an `AuthenticationVerifier`;
- the verifier receives session ID and a per-session challenge;
- protocol-major mismatch is rejected and a higher compatible peer minor is negotiated down to the current local minor;
- successful authentication binds verifier-confirmed `node_id` to an advertised node ID, when present, and to the control-envelope `actor_id`;
- later session messages must continue using that authenticated node actor;
- first-time messages require the current optimistic session revision;
- successful request IDs are fingerprinted for the session: exact replay returns the prior snapshot, changed semantic reuse is rejected;
- capability negotiation cannot add unoffered capabilities or silently drop configured required capabilities;
- profile node/revision and benchmark profile revision are bound before readiness;
- readiness is decided by an injected `BenchmarkAcceptancePolicy`; there is no accept-all default;
- drain is allowed only from `READY`;
- an external incident/revocation signal can terminate an active session.

This is not a network listener and it is not durable network-session persistence.

## M1 reference node identity

ADR 0005 is accepted for the **narrow M1 reference implementation**. `node_identity.py` implements authentication method `computemesh-ed25519-v1` using Ed25519 challenge signatures.

The signed context is domain-separated and binds:

- session ID;
- per-session challenge;
- stable node ID;
- key ID;
- protocol major/minor;
- proof issue/expiry time;
- a canonical digest of the accepted `NodeHello` semantics, including capabilities and supported authentication methods.

Reference proof policy:

- proof TTL defaults to 30 seconds and is capped at 60 seconds;
- bounded clock skew is checked;
- malformed/oversized proofs and extreme timestamps are denied rather than propagated as verifier failures;
- the verifier resolves an enrolled active public key and checks its deterministic key fingerprint before signature verification;
- successful proof returns a bounded authenticated session lifetime rather than a bearer token supplied by the node.

`services/identity/` provides the control-plane reference registry:

- random stable `node_id` independent of key rotation;
- short-lived provider-authorized enrollment tokens stored only as SHA-256;
- public Ed25519 keys only — no node private keys are stored by the control plane;
- idempotent same-token/same-key enrollment;
- rejection of token/key conflicts and duplicate key enrollment across nodes;
- key rotation with optional atomic revocation of prior active keys;
- monotonic key/node revocation;
- restart-persistent SQLite reference state.

A revoked key/node is unavailable to **new** authentication attempts. Already-authenticated sessions still require external revocation fan-out to the session termination path.

## Security boundary

The M1 reference identity is not the complete production identity system. It does **not** provide:

- provider/user login or derive `principal_id` from a network principal;
- node private-key storage;
- Windows DPAPI/CNG or Linux secret/keyring integration;
- TLS/QUIC or another authenticated transport;
- hardware attestation;
- Sybil resistance or cloned-key detection;
- active-session revocation distribution;
- rate limits/abuse controls;
- production database/high availability.

A syntactically valid `actor_id` is still not trusted until authentication succeeds. Network exposure remains blocked until transport security, service authorization, key storage, limits, and operational revocation are implemented and reviewed.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s protocol/tests -v
python -m unittest discover -s services/identity/tests -v
```

Current local evidence before cross-platform CI: **64/64 protocol tests** and **13/13 identity/integration tests** passing. Coverage includes protocol/version/actor/revision/replay failures, real Ed25519 proof verification, capability/hello tampering, expired/future/extreme proof timestamps, unknown/revoked keys, enrollment replay/conflict/expiry, duplicate-key rejection, rotation, monotonic revocation, ownership checks, restart persistence, and an enrollment → Ed25519 verifier → `NodeSessionWireHandler` integration flow.

## Remaining work

- implement OS-protected node private-key storage for supported Windows/Linux node-agent paths;
- put the reference registry behind authenticated/authorized service APIs rather than caller-supplied principal assertions;
- add active-session revocation fan-out;
- select and implement control/data transport under ADR 0003;
- bind the minimum remaining availability/job/artifact/runtime/result/failure/heartbeat messages required by the exact M1 runtime spike;
- add protocol fuzz/property coverage before production exposure.
