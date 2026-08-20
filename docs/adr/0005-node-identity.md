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

## Verification

Tests:

- successful enrollment;
- stolen/expired session credential;
- key rotation;
- revocation;
- replay;
- cloned identity detection behavior.
