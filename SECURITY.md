# Security Policy

ComputeMesh is currently in **M0 planning and research**. No production release is supported.

## Supported versions

| Version | Supported |
| --- | --- |
| No public release | N/A |

This table will be replaced when signed releases exist.

## Reporting a vulnerability

Do not publish exploit details for a suspected ComputeMesh vulnerability before a private reporting channel exists.

Until a dedicated security address/process is published:

1. contact the repository owner privately;
2. include the affected component/version/commit;
3. include reproduction steps and impact;
4. do not include real customer secrets or third-party personal data;
5. coordinate disclosure timing.

A future public alpha MUST provide a dedicated vulnerability-reporting channel and response policy.

## Security scope

High-priority security surfaces include:

- provider node agent;
- runtime worker boundary;
- protocol parsers;
- node authentication;
- model/shard verification;
- artifact cache;
- scheduler authorization;
- billing/ledger;
- release/update channel;
- telemetry/logging;
- desktop/dashboard authentication.

## V1 security invariants

- Provider nodes MUST NOT execute arbitrary customer code.
- User-controlled inputs MUST NOT select arbitrary host files, commands, binaries, containers, or dynamic native modules.
- State-changing protocol operations MUST be replay-safe.
- Model artifacts MUST be digest-verified before use.
- Production workers and updates MUST be signed.
- Update rollback and revocation MUST exist before public alpha.
- Billing entries MUST be auditable and duplicate-safe.
- Privacy tiers MUST be scheduler-enforced.
- Public-compute nodes MUST NOT be described as confidential by default.
- Logs MUST exclude raw prompts/outputs by default.
- Secrets MUST NOT be committed to the repository.

## Secure development requirements

Security-sensitive changes require:

- threat-model update where applicable;
- tests for authorization and failure paths;
- negative tests;
- bounded input sizes;
- structured errors without secrets;
- review of logs/telemetry;
- dependency review;
- ADR when changing trust boundaries or cryptographic choices.

## Release security checklist

Before a public alpha:

- signed installer;
- signed release manifest;
- reproducible or independently verifiable release build;
- SBOM/provenance;
- staged auto-update;
- rollback;
- signer/key revocation;
- anti-downgrade policy;
- node sandbox/workload-boundary review;
- protocol fuzzing;
- authn/authz review;
- privacy review;
- payment/ledger review;
- incident-response runbook;
- vulnerability-disclosure process.

## Security architecture

See:

- `THREAT_MODEL.md`;
- `docs/PRIVACY_TIERS.md`;
- `docs/FAILURE_SEMANTICS.md`;
- protocol and identity ADRs.

## Third-party runtime warning

Third-party distributed-inference/runtime features are not automatically safe for exposure to untrusted networks. ComputeMesh must wrap or isolate them according to its own authentication, authorization, workload, and transport security requirements before provider use.

## Dependency policy

When code begins:

- pin production dependencies;
- record licenses;
- generate an SBOM for release artifacts;
- scan for known vulnerabilities;
- minimize native/runtime dependencies on provider nodes;
- do not auto-enable experimental network services merely because an upstream project provides them.
