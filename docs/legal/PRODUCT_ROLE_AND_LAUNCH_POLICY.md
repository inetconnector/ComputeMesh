# ComputeMesh product-role and production launch policy

Status: mandatory engineering policy for commercial production. This document is not a legal opinion and does not replace advice from qualified German/EU counsel.

## Target product role

ComputeMesh is designed and marketed as **B2B distributed compute/orchestration infrastructure**. It is not marketed as a medical, legal, financial, employment, credit, safety or other professional decision-maker. Customer-selected third-party models remain attributed to their upstream publisher and license.

Marketing, documentation and UI must not imply that a third-party model is a proprietary "ComputeMesh LLM" or that ComputeMesh guarantees model truthfulness, professional suitability, a fixed saving, uptime, income or benchmark result.

The EU AI Act role of any concrete deployment depends on facts, including development, branding, intended purpose and how a system is placed on the market. The production launch gate therefore requires legal review rather than assuming that an infrastructure label alone determines the legal classification.

## Hard production controls

`COMPUTEMESH_PRODUCTION_MODE=1` activates fail-closed controls. Production startup is refused unless all of the following are explicitly complete:

- `COMPUTEMESH_LEGAL_REVIEW_APPROVED=1`
- `COMPUTEMESH_DPA_READY=1`
- `COMPUTEMESH_PROVIDER_AGREEMENT_READY=1`
- `COMPUTEMESH_SUBPROCESSOR_REGISTER_COMPLETE=1`
- `COMPUTEMESH_TRANSFER_ASSESSMENT_COMPLETE=1`
- `COMPUTEMESH_PAYMENT_PROVIDER=stripe`
- `COMPUTEMESH_PROVIDER_COMPLIANCE_REGISTRY=<operator-controlled JSON file>`

These flags are deployment controls, not evidence by themselves. The operator must retain the underlying signed/current documents and review records.

## Provider admission

Production scheduling defaults to EEA providers only. A provider is schedulable only when its Ed25519 `node_id` has an active record in the server-owned compliance registry containing:

- EEA operating country;
- verified business status;
- current Terms acceptance;
- provider data-processing/confidentiality obligations accepted;
- no-prompt/no-response plaintext logging obligation attested;
- approved payout processor (`stripe_connect` or `none` while unpaid/testing).

Provider-supplied node telemetry cannot grant these permissions. Account registration also does not grant node admission.

The default EEA-only rule is a risk-minimizing deployment policy, not a statement that every EEA processing arrangement is automatically GDPR-compliant. Subprocessor authorization, Art. 28 terms, TOMs and the actual data flow still require review.

## Workload-data policy

Provider software must not persist or log plaintext prompts/responses. The public provider control agent receives hardware/runtime evidence and execution-attestation documents bound to hashes and job identifiers; it must not add prompt/message payloads to its control protocol or logs.

This does not justify claiming that arbitrary distributed execution is incapable of exposing workload-derived data. Data-plane security, host security, memory access, debugging and the actual runtime architecture must be assessed before sensitive workloads are admitted. Special-category, professional-secret or similarly sensitive processing requires a deployment-specific assessment.

## Model provenance

Production live-model manifests must contain `upstream.publisher`, `upstream.model_name`, `upstream.source` and explicit license ID/source. Model IDs should preserve publisher/model identity rather than rebranding third-party models as proprietary ComputeMesh models.

## Payments and balances

Commercial customer funding uses the configured regulated payment-service-provider integration. The legacy direct stablecoin-crediting module is research-only and refuses to initialize in production mode.

Internal customer/provider ledger balances are accounting records for service settlement; they must not be marketed as bank deposits, e-money, investment products or freely transferable customer wallets. Provider production payouts are onboarded through the approved payout processor and remain subject to verification, settlement and compliance rules.

## Browser privacy

Production portal policy is first-party by default. Third-party analytics, advertising, fonts, scripts or storage must not be introduced without privacy/TDDDG review and, where required, a valid consent mechanism. The existing language preference is documented separately in the Privacy Policy.

## Change control

Any proposed change involving one of the following requires renewed legal/privacy review before production activation:

- consumer access;
- non-EEA workload processing;
- a proprietary/rebranded model;
- high-risk or regulated intended purposes;
- prompt/response persistence or provider debugging access;
- a new subprocessor or hosting country;
- direct crypto/customer-money custody or transferable balances;
- new analytics/advertising/tracking;
- fixed SLA, savings, income, medical/legal/safety or accuracy claims.
