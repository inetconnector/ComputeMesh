# ComputeMesh Privacy Tiers

**Status:** Draft v0.1

Privacy tiers are enforceable scheduling policies. They are not marketing labels.

## 1. General rule

Encrypted transport protects data **between** endpoints. It does not protect plaintext while a provider-controlled runtime is processing it.

Therefore ComputeMesh MUST distinguish:

- transport security;
- operator/location policy;
- execution confidentiality.

## 2. `public_compute`

Eligible:

- consumer/community provider nodes;
- approved general providers.

Assumption:

- provider administrator or malware on the host may be able to inspect prompts, activations, KV state, or model outputs accessible to the process.

Guarantees:

- authenticated/encrypted transport;
- workload-boundary controls;
- telemetry minimization.

Does not guarantee:

- confidential execution;
- geographic restriction unless separately specified.

## 3. `region_verified`

Eligible:

- nodes whose region/operator evidence meets the configured policy.

Adds:

- geographic/operational placement constraint.

Does not inherently add:

- hardware memory confidentiality.

Naming should use explicit region where possible, e.g. `eu_region_verified`, rather than implying legal compliance from one flag.

## 4. `datacenter_only`

Eligible:

- approved datacenter-class providers.

Adds:

- provider-class restriction;
- potentially stronger operational controls/SLA.

Does not automatically guarantee:

- prompt confidentiality from provider operator;
- confidential accelerator memory.

## 5. `confidential_compute`

Disabled as a product guarantee until a concrete implementation exists.

To enable it, an ADR/security design must define:

- supported TEE/confidential GPU/CPU;
- remote attestation;
- measured software identity;
- key release;
- model/input encryption flow;
- accelerator-memory assumptions;
- side-channel scope;
- rollback/replay protection;
- attestation failure behavior.

The scheduler MUST reject the tier when no eligible attested capacity exists rather than silently downgrade.

## 6. Mixed-stage policy

A job's effective privacy is no stronger than its weakest participating stage.

Sensitive jobs must not route some stages through public nodes unless the policy explicitly allows that exposure.

## 7. Logging

For all tiers, default platform logs exclude raw prompts/outputs.

Higher tiers may impose stricter:

- telemetry fields;
- retention;
- operator access;
- regional storage.

## 8. User/API behavior

If requested privacy cannot be satisfied:

- reject with machine-readable reason;
- optionally suggest weaker tiers only if the user explicitly permits downgrade;
- never silently relax privacy.
