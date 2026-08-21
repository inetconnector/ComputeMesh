# ADR 0005: Node Identity and Key Lifecycle

- **Status:** Accepted for M1 reference implementation
- **Date:** 2026-08-21

## Context

Provider nodes need a stable identity without equating software signing with host trust. The identity must survive IP changes and routine key rotation, bind node sessions to an enrolled provider principal, resist replay/downgrade of the unauthenticated hello/auth exchange, and support explicit revocation.

The threat model still assumes a provider host may be compromised. Node identity authenticates an enrolled key; it does not prove that the host, runtime, benchmark report, or workload result is honest.

## Decision

### Stable identity

- The control plane assigns each enrolled node a random stable `node_id`.
- `node_id` is independent of the current cryptographic key so key rotation does not erase reputation/history.
- A provider principal owns the node binding in the identity registry.
- IP address, hostname, hardware serials, and GPU UUIDs are not identity roots.

### M1 node key

- M1 node signing keys use **Ed25519**.
- Public keys are raw 32-byte Ed25519 public keys.
- `key_id` is `ed25519:` followed by base64url(SHA-256(raw-public-key)).
- The identity service stores public keys and key state only; node private keys are never uploaded to the identity database.

Ed25519 was selected because it is a compact deterministic signature scheme standardized by RFC 8032, included as EdDSA in NIST FIPS 186-5, and directly supported by the current Python `cryptography` implementation used by the reference prototype. This decision is for the M1 node challenge proof and does not require the eventual transport certificate format to use the same key type.

### Enrollment

- Enrollment is authorized out-of-band by an already authenticated provider principal.
- The reference control plane issues a cryptographically random one-time enrollment token with 256 bits of random material.
- Enrollment token lifetime is bounded to **15 minutes**.
- The database stores only SHA-256(token), not the bearer token itself.
- The node generates its key pair locally and enrolls only the public key.
- Successful enrollment creates the stable random `node_id` and initial active `key_id`.
- Retrying a consumed token with the **same** public key is idempotent and returns the same node/key binding.
- Reusing a consumed token with a **different** public key is an enrollment conflict.

The reference SQLite implementation is not itself an enrollment network endpoint. The future service boundary must authenticate/authorize the provider principal before token issuance, rotation, or revocation.

### Session proof

The advertised authentication method is:

```text
computemesh-ed25519-v1
```

`NodeAuthenticate.credential` remains an opaque string to the generic session layer. For this method it contains a bounded base64url-encoded strict proof document with:

- version;
- `node_id`;
- `key_id`;
- integer UTC `issued_at`/`expires_at` epoch seconds;
- Ed25519 signature.

Default proof lifetime is **30 seconds** and the verifier rejects proof lifetimes over **60 seconds**. Maximum allowed future clock skew is **30 seconds**.

The signature does not sign arbitrary caller-provided JSON. It signs a domain-separated, length-delimited binary context containing:

- `session_id`;
- server-issued per-session challenge;
- `node_id`;
- `key_id`;
- NodeHello protocol major/minor;
- proof issued/expiry times;
- SHA-256 of the normalized NodeHello semantics (agent version, platform, optional node ID, advertised auth methods, and capabilities).

Consequences:

- a proof captured from one session cannot authenticate another session because the session ID/challenge differ;
- tampering with the NodeHello identity/capabilities/protocol context invalidates the proof;
- generic envelope `actor_id` is still checked against the verifier-confirmed `node_id` before the session advances;
- replay protection still also uses request IDs, envelope expiry, and session revisions.

After successful proof verification the reference verifier grants a bounded **15-minute authenticated session lease**. Key/node revocation may terminate a live session earlier through the existing external session-termination path.

### Rotation and revocation

- The stable `node_id` remains unchanged during key rotation.
- A new key can be added for the same provider-owned node.
- The reference rotation operation can atomically revoke prior active keys.
- Revocation is monotonic: a revoked key is not reactivated by presenting the same public key again.
- A revoked node makes all of its keys unavailable to new authentication attempts.
- Active-session revocation fan-out is a required service responsibility; the local SQLite registry does not own network sessions.

### Private-key storage

The cryptographic protocol is separated from platform key storage.

Required policy:

- **Windows provider agent:** use per-user Windows DPAPI/CNG-backed protection for exported node private-key material or a stronger non-exportable CNG/TPM provider when implemented. Do not use machine-wide DPAPI as the default because it allows other local users on the machine to decrypt the protected blob.
- **Linux desktop provider agent:** use Secret Service/keyring storage when a real login-session Secret Service is available.
- **Headless Linux M1 lab:** a strict-permission local key file may be used only as an explicitly labeled lab fallback. It is **not sufficient for public provider release**.
- Public headless Linux provider release remains blocked until an OS-/hardware-backed key-storage implementation (for example TPM2 or another reviewed host-bound provider) is implemented and tested.

The current commit implements the signing/verifier and public-key registry, not the final node-side storage adapters.

### Transport relationship

This ADR does **not** replace transport security. ADR 0003 must still select authenticated encrypted control/data transport. The node challenge proof gives application/session identity and downgrade/replay binding; it does not provide confidentiality or traffic encryption.

### Attestation and Sybil limits

- Ed25519 identity does not attest boot state, agent binary, GPU, or TEE state.
- A copied private key can authenticate from more than one host. Cryptography alone cannot distinguish those clones.
- Concurrent-session, device/network, payment/economic, reputation, and later attestation signals may be used for clone/Sybil risk, subject to privacy/legal policy.
- `confidential_compute` remains unavailable without a separate accepted attestation/TEE design.

## Reference implementation

- `protocol/node_identity.py`
  - `computemesh-ed25519-v1` proof creation/parsing;
  - domain-separated challenge signing context;
  - Ed25519 verifier implementing the existing `AuthenticationVerifier` boundary;
  - proof TTL/skew/signature/key-fingerprint checks.
- `services/identity/store.py`
  - SQLite reference enrollment token, stable node identity, public key registry, rotation, revocation, and verifier key lookup.
- `services/identity/tests/`
  - enrollment/lifecycle persistence and end-to-end enrollment → session authentication integration.

The generic `NodeSession` still has no permissive default verifier; callers must explicitly choose/inject this verifier or another future accepted mechanism.

## Verification

Current local evidence:

- full protocol suite including node identity: **63/63 passing**;
- identity-store/integration suite: **11/11 passing**;
- relevant identity Python files pass `py_compile`.

Covered failure/evidence cases include:

- valid enrolled challenge proof;
- session/challenge replay mismatch;
- NodeHello tampering/downgrade context mismatch;
- expired proof;
- excessive proof TTL;
- future timestamp outside skew;
- malformed proof field types without verifier crash;
- signature tampering;
- unknown/revoked key;
- one-time enrollment replay/idempotency conflict;
- expired enrollment token;
- stable identity across rotation;
- revoked-key non-reactivation;
- node revocation;
- wrong provider principal for lifecycle mutations;
- SQLite restart persistence;
- real Ed25519 enrollment → `NodeSessionWireHandler` authentication integration.

Still required before public alpha:

- authenticated provider-facing enrollment/rotation/revocation API;
- node-side production key storage on Windows and Linux targets;
- active-session revocation distribution;
- transport binding under ADR 0003;
- rate limiting/abuse controls and audit events;
- cross-process/real-machine key lifecycle tests;
- cloned-key/concurrent-session risk controls;
- independent security review/fuzzing.

## Consequences

Positive:

- stable node reputation survives key rotation;
- proof replay is bound to a server challenge and exact hello/protocol context;
- the control plane stores no node private key;
- the mechanism is small enough to test thoroughly before adding transport complexity;
- transport and key-storage implementations remain replaceable behind explicit boundaries.

Costs/risks:

- adds a maintained cryptographic dependency (`cryptography`);
- rotation/revocation now require a real identity service and live-session notification path;
- headless Linux production storage remains an explicit blocker;
- cloned private keys are still possible on compromised hosts;
- this mechanism authenticates identity only and must not be represented as host integrity or confidential computing.
