# ADR 0005: Node Identity and Key Lifecycle

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

Provider nodes need a stable identity without equating software signing with host trust.

## Proposed decision

Each enrolled node receives/creates a node key pair and stable `node_id`.

Requirements:

- private key stored using OS-protected storage where practical;
- enrollment binds node to provider principal;
- sessions use short-lived authenticated credentials;
- node key can be rotated/revoked;
- reinstall/re-enrollment behavior is explicit;
- node reputation belongs to stable node identity/evidence, not IP address.

## Non-goal

Node identity does not prove the host is uncompromised or that one operator controls only one node identity.

## M0 implementation note — 2026-08-21

`protocol/node_session.py` now provides a transport-neutral **semantic skeleton** for the documented node-session lifecycle. It requires an injected verifier, provides a per-session challenge, enforces credential expiry, checks an advertised stable node ID against the authenticated identity, negotiates capabilities, gates readiness on profile/benchmark consistency, and supports external session termination for a revocation signal.

This implementation deliberately does **not** accept this ADR or choose the security mechanism. In particular, it does not select:

- key/signature algorithm;
- credential/token format;
- enrollment or issuer protocol;
- OS key-storage API;
- rotation/revocation distribution mechanism;
- transport authentication mechanism;
- hardware attestation.

There is no permissive default verifier. Production network exposure remains blocked until the concrete identity/key lifecycle is selected, implemented, and reviewed.

## Verification

Required final tests/evidence remain:

- successful enrollment using the selected production mechanism;
- stolen/expired session credential;
- key rotation;
- revocation;
- replay;
- cloned identity detection behavior.

The M0 semantic test suite currently covers successful verifier-gated session progression, expired credentials, identity mismatch, challenge/verifier binding, capability mismatch, profile/benchmark revision mismatch, and external termination. These tests validate session semantics only, not the eventual cryptography or identity backend.
