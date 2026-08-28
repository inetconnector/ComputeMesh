# ADR-0008: Orthogonal provider trust and execution privacy

- **Status:** Accepted
- **Date:** 2026-08-28

## Decision

ComputeMesh separates provider trust (`OPEN`, `VERIFIED`, `RESTRICTED`) from execution privacy (`PUBLIC`, `CONFIDENTIAL`, `CRYPTO_PRIVATE`). Routing evaluates the intersection of hardware/model compatibility, trust, region/customer policy, privacy requirements, attestation and network constraints.

`PUBLIC` is the only class that may use an `OPEN` provider. This enables a global heterogeneous GPU pool after technical admission. Region restrictions remain first-class policy and can narrow that pool.

`CONFIDENTIAL` and `CRYPTO_PRIVATE` are fail-closed feature-gated modes. They are disabled by default. No privacy downgrade is allowed. TLS, containers, VM isolation and model sharding are not treated as confidential inference.

Confidential execution requires a concrete technology-specific attestation verifier. The public repository provides envelope validation and verifier registration only; an unregistered or simulated technology is rejected.

Content keys are never gateway/control-plane material. Key release must bind to the attested node, nonce and ephemeral public key, with no universal master key.

## Compatibility

The existing EEA/business-verified production gate remains unchanged as the default B2B compliance path. The global `PUBLIC` pool is an explicit policy path, not a weakening of that default.
