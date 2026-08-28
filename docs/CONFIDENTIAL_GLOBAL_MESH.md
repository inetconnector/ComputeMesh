# Confidential Global Mesh

ComputeMesh now models **provider trust** and **execution privacy** as orthogonal policy dimensions.

## Trust tiers

- `OPEN`: technically admitted community/global provider. Eligible only for workloads whose policy explicitly permits it.
- `VERIFIED`: provider identity/compliance controls verified for the applicable product policy.
- `RESTRICTED`: a narrower contract/customer/region-controlled provider pool.

## Privacy classes

- `PUBLIC`: input/output is allowed to be processed on ordinary admitted workers. This class can use heterogeneous GPUs globally when hardware/model/network and job policy match.
- `CONFIDENTIAL`: protected execution. Feature flag defaults OFF and requires a concrete technology-specific attestation verifier, fresh attestation, non-OPEN trust and no plaintext logging.
- `CRYPTO_PRIVATE`: cryptographic private execution. Feature flag defaults OFF and every requested crypto capability must be present.

Trust does not imply privacy, and privacy requirements do not imply geography. Region/customer restrictions remain separate policy predicates.

## Scheduler rule

Eligibility is the intersection of model compatibility, hardware/runtime admission, trust tier, privacy class, region/customer constraints, attestation/crypto capability and network requirements. An empty intersection fails closed. The scheduler must never silently retry a protected job as `PUBLIC`.

## Confidential attestation

The public code validates an attestation envelope containing `node_id`, concrete `technology`, `measurement`, `runtime_digest`, attested ephemeral public key, nonce, validity interval and `debug_disabled`. Validation alone does not create a confidential provider: a concrete verifier must be registered. Unknown, generic or simulated technologies are rejected.

TLS, containers, VMs and ordinary sharding are transport/isolation mechanisms and must not be marketed or represented as confidential inference.

## Key release

Content keys remain client-side or in a dedicated future key-release service. Ordinary gateway/control-plane code has no content-key decrypt/master-key path. Any release target must match the attested node, nonce and ephemeral public key.

## Backward-compatible production posture

The existing EEA/business-verified B2B production gate remains the default and is not weakened. The global `PUBLIC` pool is an explicit additional routing policy. `COMPUTEMESH_CONFIDENTIAL_EXECUTION_ENABLED` and `COMPUTEMESH_CRYPTO_PRIVATE_ENABLED` default to disabled.
