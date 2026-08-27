# ComputeMesh Technical and Organisational Measures (TOMs)

Purpose: baseline for Art. 32 GDPR and Art. 28 processor documentation. This file describes required controls. Production evidence must verify that they are actually enabled.

## 1. Confidentiality

- Role-based/least-privilege access to production systems, repositories, billing, identity and private control-plane state.
- SSH/private signing/provider keys are never committed to source control.
- Provider private identity keys remain on provider systems by design; central systems store public identity material.
- Sensitive registration metadata is encrypted with AES-256-GCM where the current identity vault is used.
- Secrets are injected from deployment secret storage/environment rather than embedded in source.
- Production inference content is not to be exposed to operator/provider personnel beyond what is technically necessary and authorized.
- Access to prompt/output content for debugging is disabled by default unless a documented incident or customer-approved process requires it.

## 2. Integrity

- TLS/authenticated transport for externally exposed production interfaces; certificates and hostname verification must not be bypassed.
- Ed25519 identity/signature mechanisms for provider/control-plane evidence where implemented.
- Signed placement/execution plans and verification/evidence bindings are used on the production path where applicable.
- Billing uses append-only/double-entry foundations with idempotency controls.
- Stripe webhook processing must verify signatures before financial crediting.
- Source changes use version control, CI and reviewable pull requests.

## 3. Availability and resilience

- Fail-closed behavior when required models, identity state, control-plane credentials or real inference runtimes are unavailable.
- Backup/restore procedures must exist for production identity, accounting, settlement and required evidence stores.
- Recovery procedures must be tested periodically, including control-plane restart, billing outbox replay and provider reconnect where relevant.
- Capacity/retry mechanisms must avoid silent duplicate settlement.

## 4. Separation and purpose limitation

- Public provider/runtime code is separated from private production policy and sensitive control-plane state.
- Development/test state is separated from production state.
- Promotional/test credits are not to be treated as real provider cash liabilities unless backed by the applicable settlement rules.
- Customer-content processing is separated conceptually and contractually from operator account/billing/security processing.

## 5. Data minimisation

- Persist digests/evidence/operational metadata rather than raw prompt/output content where full content is not required.
- Do not add telemetry fields merely because they are technically available; document purpose and retention first.
- Do not enable behavioral analytics, advertising pixels or device fingerprinting by default.
- API-key persistence uses masked contact metadata where full contact data is not required for the gateway key store.

## 6. Access and authentication

- Unique operator identities for administrative access; shared root/admin accounts are prohibited except documented break-glass recovery.
- Strong authentication and, where supported, MFA for GitHub, hosting, Stripe and administrative services.
- API/provider credentials are rotatable and revocable.
- Production SSH uses key-based authentication and restrictive filesystem permissions.

## 7. Logging and monitoring

- Maintain an inventory of all production logs: application, reverse proxy, CDN/WAF, operating system, database, Stripe/webhooks and provider control.
- Logs must not contain private keys, raw authorization headers, full payment credentials or unnecessary prompt/output content.
- Security-relevant events should be detectable without creating unlimited data retention.
- Log retention must follow the retention schedule and incident/legal-hold rules.

## 8. Vulnerability and change management

- CI compile/test/lint checks run before merge.
- Dependencies and upstream runtimes (including llama.cpp and Stripe SDK/API versions) require controlled upgrade/revalidation.
- Security-sensitive changes require threat/privacy impact review.
- Internet-facing llama.cpp RPC must not be exposed without an appropriate authenticated security layer.

## 9. Incident and breach management

Production operation must provide:

1. an incident contact and escalation path;
2. containment and evidence-preservation steps;
3. assessment whether personal data was affected;
4. risk assessment for individuals;
5. controller/customer notification obligations where acting as processor;
6. supervisory-authority notification assessment under Art. 33 GDPR;
7. data-subject notification assessment under Art. 34 GDPR;
8. post-incident remediation and documentation.

## 10. Testing and review

- Periodically test restoration, credential revocation, unauthorized access controls and provider isolation.
- Review TOM effectiveness after material architecture changes or incidents.
- Penetration/security testing must use authorized targets and avoid production customer data unless explicitly scoped.
- Maintain evidence that the implemented controls match this document.

## 11. Production deviations

Any production deviation from these TOMs must have an owner, documented risk assessment, compensating control where possible, target remediation date and approval appropriate to the risk.