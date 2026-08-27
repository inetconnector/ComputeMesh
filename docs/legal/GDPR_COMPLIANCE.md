# ComputeMesh GDPR / DSGVO Production Compliance Gate

Status: **mandatory pre-production control**

This document is an engineering/compliance control, not a legal opinion. A production deployment that processes personal data must not be represented as "GDPR compliant" merely because this repository contains a privacy notice. Compliance depends on the deployed configuration, actual processors/subprocessors, contracts, retention, security controls and operational practice.

## Hard launch gates

Before commercial production processing of personal data, all applicable items below must be completed and evidenced:

- [ ] Controller/operator identity and all mandatory Impressum details verified; no placeholder register, VAT, W-IdNr or supervisory information remains where legally required.
- [ ] Current Privacy Policy matches the deployed data flows, logs, hosting, payment services, providers and browser storage.
- [ ] Current Terms version is used by registration and acceptance is stored with version + timestamp.
- [ ] Business-customer processing role assessed per use case (controller vs processor).
- [ ] Art. 28 GDPR DPA/AVV executed with business customers where ComputeMesh processes personal data on their documented instructions.
- [ ] Processor/subprocessor register completed with purpose, location, role and contract status.
- [ ] Any subprocessor used for processor activities is bound to equivalent Art. 28 obligations.
- [ ] International transfers documented; Chapter V mechanism and supplementary measures recorded where required.
- [ ] Record of Processing Activities (RoPA/VVT) completed and maintained.
- [ ] Retention/deletion schedule implemented in real storage, not only documented.
- [ ] Data-subject request process for access, rectification, erasure, restriction, portability and objection tested.
- [ ] Art. 32 technical and organisational measures implemented and reviewed against the deployed environment.
- [ ] Incident response and personal-data-breach assessment/notification procedure tested.
- [ ] DPIA screening completed; if Art. 35 GDPR threshold is met, a DPIA is completed before the relevant processing.
- [ ] Cookie/local-storage inventory completed. Non-essential terminal-device access is disabled until a valid consent mechanism exists where required by § 25 TDDDG.
- [ ] No advertising/behavioral analytics/fingerprinting is enabled without a corresponding legal basis, consent flow where required, and updated disclosure.
- [ ] Production reverse proxy / CDN / WAF / host logging inventory is documented. No "zero log" claim is made unless technically verified end-to-end.
- [ ] Stripe Checkout/Connect production account, privacy roles, KYC flows and applicable processing/transfer arrangements are documented.
- [ ] Provider workload-data access is assessed. Provider contracts, confidentiality/data-processing role and geography are compatible with customer workloads.
- [ ] Special-category/high-risk data policy is defined. Default public/pre-production service must not invite such data.
- [ ] Secrets/private keys are excluded from repositories and operational access follows least privilege.

## Current audited data flows

The current codebase can process at least:

1. Registration: email address, role, optional payout wallet metadata, account/API-key identifiers, Terms/privacy acknowledgement and business-user confirmation.
2. Portal/API security: client IP and request/security metadata used for rate limiting and abuse prevention.
3. Inference: full request messages/prompts transmitted to the configured inference runtime; generated output returned to the caller; execution/evidence metadata can be persisted.
4. Provider operations: node identity/public keys, hardware inventory, runtime/build data, benchmarks, heartbeats, network/runtime telemetry, job/evidence/attestation metadata.
5. Billing: customer/provider ledger records, Stripe Checkout identifiers, webhook events, Stripe Connect account/onboarding/transfer/settlement metadata.
6. Browser storage: language preference in `localStorage` (`cm_portal_lang`).

## Default privacy posture

- Data minimisation by default.
- No promise of absolute zero logging.
- No promise that distributed providers cannot access workload data.
- No non-essential tracking by default.
- No raw card data handled by application code when hosted Stripe Checkout is used.
- Explicit B2B Terms acceptance before credential issuance.
- Personal-data inference for business customers requires role assessment and, where applicable, an Art. 28 DPA.
- Production provider selection must support legally appropriate geography/provider constraints before sensitive workloads are accepted.

## Change management

Any material change to the following requires a legal/privacy re-review before production deployment:

- new inference runtime or model provider;
- new hosting/CDN/WAF/analytics provider;
- new payment or payout provider;
- new provider geography or third-country processing;
- persistence of prompt/output content;
- new telemetry fields or device fingerprinting;
- consumer/B2C offering;
- automated decisions with legal or similarly significant effects;
- processing of special-category data;
- new purpose for existing personal data.

## No self-certification claim

Do not publish "GDPR certified", "100% GDPR compliant", "zero risk", "zero log" or equivalent absolute claims unless a specific, current and supportable certification/audit actually exists. The repository provides compliance controls; operational compliance must be demonstrated continuously.