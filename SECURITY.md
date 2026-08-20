# Security Policy

ComputeMesh is in planning/bootstrap state. No production node, scheduler, runtime, or API is available yet.

## Supported Versions

No released versions are currently supported.

## Reporting Security Issues

Until a formal disclosure channel exists, do not publish sensitive vulnerability details publicly. Open a private issue or contact the repository owner directly.

## V1 Security Commitments

- Provider nodes must not run arbitrary customer code.
- Workers and updates must be signed before public release.
- Model shards must be hash-addressed and signed.
- Billing and verification events must be auditable.
- Privacy tiers must be enforced by scheduling policy.
- Logs and crash reports must minimize prompt, output, and personal data.

## Required Before Public Alpha

- signed installer
- reproducible release build process
- automatic update with rollback
- node sandboxing and workload boundary review
- supply-chain review
- incident response process
- security disclosure process
- privacy, payment, and terms review
