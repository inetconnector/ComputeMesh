# ComputeMesh Retention and Deletion Schedule

Status: production baseline. Actual periods must be confirmed against German/EU tax, commercial, accounting, contract, limitation and security requirements for the deployed business model.

## Principles

- Retain only for a defined purpose and period.
- Prefer deletion or irreversible anonymisation once no longer necessary.
- Legal holds suspend deletion only for affected data and only as long as necessary.
- Backups must age out under a defined rotation; deleted data must not be reintroduced into ordinary production processing by restore.
- Customer-content retention and operator accounting/security retention are separate purposes and must not be conflated.

## Baseline schedule

| Data class | Default operational rule | Deletion trigger / exception |
| --- | --- | --- |
| Raw prompt/message and generated output content | Do not persist by default beyond technically necessary request processing unless the deployment explicitly requires persistence | Delete after request completion/transient processing; exception only for documented customer feature, incident handling or legal obligation |
| Request routing/job metadata | Keep only as long as needed for service operation, reconciliation, debugging and dispute handling | Delete/anonymise after configured operational/claim period unless linked to unresolved incident/settlement/legal hold |
| Execution evidence, digests and attestations | Retain for verification, fraud investigation, billing/settlement and reproducibility needs | Delete/anonymise after settlement/claim/audit need expires; do not retain raw customer content merely because evidence is retained |
| Account/contact data | Contract/account lifetime | Delete/anonymise after account closure when no longer required for claims, legal obligations or security records |
| Terms/privacy acceptance record | Contract lifetime plus applicable period for proving contract formation/claims | Delete when evidence purpose and legal claim period expire |
| API-key metadata | Active credential lifetime | Delete/revoke after credential/account termination once no longer needed for abuse/security evidence |
| Provider node/public-key/profile data | Provider relationship and operational need | Delete/anonymise after provider offboarding and applicable verification/claim period |
| Provider hardware/benchmark/telemetry | Current operational/performance/fraud need | Aggregate/anonymise where possible; delete personal/linkable data when node/provider relationship and claim need expire |
| Security/rate-limit/IP metadata | Short proportionate security window | Delete on expiry unless associated with incident, abuse investigation or legal hold |
| Ledger/billing/accounting records | Statutory and contractual accounting/claim retention | Do not delete where commercial/tax law requires retention; restrict access instead |
| Stripe session/customer/payment/transfer/webhook metadata | Reconciliation, dispute, accounting and legal retention | Delete when statutory/payment-dispute/claim period expires and no legal hold remains |
| Support communications | Until issue is resolved plus reasonable claim period | Delete/anonymise after purpose expires unless required for legal claim/compliance |
| GDPR request records | Maintain enough evidence to demonstrate handling and protect against repeat disclosure | Delete after accountability/claim purpose expires |
| Consent/cookie records if non-essential tracking is introduced | As long as needed to demonstrate consent and respect withdrawal | Delete/anonymise when proof purpose expires; withdrawal must stop future access immediately where applicable |

## Implementation requirements

Production must define machine-enforceable settings for every persistent store, including:

- database/table/file path;
- data owner;
- purpose;
- exact retention duration;
- deletion/anonymisation job;
- backup retention;
- legal-hold mechanism;
- export/DSAR path;
- processor/subprocessor deletion behavior.

A retention period is not implemented merely because it appears in this document.

## Account deletion workflow

1. authenticate/verify requester where necessary;
2. identify controller data and customer-controlled processor data separately;
3. revoke credentials and stop active processing;
4. export data where requested/applicable before deletion;
5. delete data not subject to legal retention;
6. restrict retained statutory/claim data from ordinary use;
7. propagate deletion/return instructions to processors/subprocessors where applicable;
8. record completion and any lawful exceptions;
9. allow backups to age out under documented rotation.

## Provider offboarding workflow

- revoke node credentials and provider access;
- stop new workload assignment;
- complete/resolve outstanding settlement/fraud investigations;
- remove unnecessary live telemetry/profile data;
- retain only records necessary for accounting, disputes, security and legal claims;
- instruct subprocessors where applicable.

## Review

Reassess this schedule before commercial launch and whenever new logging, analytics, model/provider integrations, storage systems or payment flows are introduced.