# Node Identity Reference Service

**Status:** M1 reference implementation; not a production network service.

## Purpose

Provide the control-plane half of the accepted M1 node identity/key-lifecycle decision:

- one-time provider-authorized enrollment tokens;
- stable node IDs independent of key rotation;
- enrolled Ed25519 public keys;
- key lookup for the node-session verifier;
- explicit key rotation and revocation state.

The implementation is intentionally a local SQLite reference store. It is not an HTTP/gRPC service and it does not authenticate the human/provider principal that calls its methods.

## Current flow

1. An already authenticated control-plane caller creates a short-lived enrollment token for a provider principal.
2. A node generates an Ed25519 key pair locally and sends only its raw public key with that token.
3. `SQLiteIdentityStore.enroll()` assigns a random stable `node_id` and records the public key under a deterministic fingerprint `key_id`.
4. The enrollment token is stored only as SHA-256 and expires after at most 15 minutes.
5. Replaying the same consumed token with the same public key returns the original node/key binding; reusing it with a different public key is rejected.
6. During a node session, `protocol.node_identity.Ed25519ChallengeVerifier` resolves the active public key from this store and verifies the short-lived session challenge proof.

## Key lifecycle

- A node ID is stable across key rotation.
- Rotation may install a new active key and revoke previous active keys atomically.
- Revocation is monotonic: a revoked key cannot be reactivated through rotation.
- Revoking a node makes all its keys unavailable to new authentication attempts.
- Existing authenticated sessions still require an external revocation signal to call the session termination path; the current store does not own active network sessions.

## Security boundary

The database stores **public keys only**. It never stores node private keys.

The `principal_id` arguments to rotation/revocation methods are authorization assertions from the caller. A future network service MUST derive them from authenticated control-plane identity rather than trust arbitrary request fields.

This reference component does not provide:

- provider/user login;
- private-key storage on the node;
- TLS/QUIC or another authenticated transport;
- hardware attestation;
- Sybil resistance;
- active-session revocation fan-out;
- rate limits or abuse controls;
- production database/high availability.

A cloned private key remains cryptographically the same node identity. Concurrent-session/device/network/economic signals are required to detect or limit clones; Ed25519 signatures alone cannot prove one physical machine.

## Tests

```powershell
python -m unittest discover -s services/identity/tests -v
```

Current local evidence: enrollment replay/conflict/expiry, rotation, monotonic key revocation, node revocation, principal mismatch, restart persistence, and a real Ed25519 enrollment → `NodeSessionWireHandler` authentication integration flow.
