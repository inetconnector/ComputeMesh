# ComputeMesh Record of Processing Activities (RoPA / VVT) Baseline

Owner: privacy/compliance owner for the production deployment

This is the repository baseline for the Art. 30 GDPR record. It must be completed with actual production processors, systems, locations, retention periods and contacts before launch.

| Processing activity | Data subjects | Personal data / metadata | Purpose | Likely legal basis / role | Recipients | Default retention rule | Required production evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Portal account registration | Customer/provider contacts | Email, role, masked optional payout destination, account/API-key metadata, Terms/privacy acceptance version/time | Account creation, authentication, contract evidence | Art. 6(1)(b)/(f), controller | Hosting/admin personnel as required | Contract duration + legally required claim/evidence period | Storage path, access matrix, deletion job |
| Portal/API abuse prevention | Visitors/API users | IP address, timestamps, rate-limit/security metadata | Security, abuse/fraud prevention, service resilience | Art. 6(1)(f), controller | Hosting/WAF/security providers if used | Short proportionate security period unless incident/legal hold | Reverse-proxy/WAF log inventory + configured retention |
| Inference execution | Customer users / persons represented in submitted content | Prompts/messages, output, routing metadata, model/job identifiers | Perform requested inference | Art. 6(1)(b) for platform relationship; often processor under Art. 28 for customer content | Configured inference runtime and assigned compute resources | Content: minimise/transient by default; metadata/evidence per operational need | DPA, customer instructions, provider/data-residency constraints |
| Execution evidence and verification | Customer/provider users | Job IDs, node IDs, timings, digests, attestations, runtime/build metadata | Integrity, fraud prevention, settlement, technical audit | Art. 6(1)(b)/(f), controller or processor depending on context | Operator, assigned provider(s), audit/security personnel | Defined operational/claim period | Field inventory + retention/deletion implementation |
| Provider enrollment and telemetry | Provider contacts/node operators | Node ID, public key, IP/network metadata, hardware inventory, runtime/build, benchmark, heartbeat/availability telemetry | Provider identity, capacity, routing, security and verification | Art. 6(1)(b)/(f), controller | Operator infrastructure; customer-visible data only where necessary | Provider relationship + operational/claim period | Provider agreement + telemetry schema + deletion process |
| Customer billing/ledger | Customer/provider contacts | Account ID, balances, metering records, billing events | Billing/accounting and settlement | Art. 6(1)(b)/(c), controller | Accounting/tax advisers as required | Applicable statutory commercial/tax period | Ledger retention rule + export/erasure exception handling |
| Stripe Checkout | Paying customer/contact | Stripe session/customer/payment-intent identifiers, transaction metadata | Payment collection, reconciliation, fraud handling | Art. 6(1)(b)/(c)/(f), roles depend on Stripe activity | Stripe and payment ecosystem | Statutory/payment-dispute periods | Stripe role/contract/transfer documentation |
| Stripe Connect provider onboarding/payout | Provider/representatives | Connected-account IDs, KYC/status metadata, transfer/settlement records | Provider eligibility and payout | Art. 6(1)(b)/(c)/(f), roles depend on Stripe activity | Stripe | Statutory/payment-dispute periods | Stripe Connect documentation + payout policy |
| Support/legal requests | Contacts/data subjects | Email, messages, account identifiers, request verification | Support, GDPR requests, disputes/legal claims | Art. 6(1)(b)/(c)/(f) | Professional advisers/authorities where required | Matter duration + legal claim/retention period | Ticket/export process + DSAR register |
| Browser language preference | Portal visitors | Preferred language stored locally on device | Remember requested UI language | § 25(2) TDDDG necessity assessment; GDPR only if personal data context applies | User device/browser | Until user/browser removes storage or preference is replaced | Storage inventory and no non-essential tracking without consent |

## Processor/subprocessor register fields

For every external service or independent distributed provider that can process personal data, record:

- legal entity and service name;
- role (processor, subprocessor, independent controller, joint controller, independent recipient — do not guess);
- exact processing purpose and data categories;
- data-center/provider geography;
- EEA/third-country status;
- Art. 28 contract status where applicable;
- Chapter V transfer mechanism where applicable;
- subprocessor authorization/change process;
- security assessment/TOM evidence;
- retention/deletion behavior;
- incident notification contact;
- contract termination and data-return/deletion procedure.

## Review cadence

Review this record at least after every material architecture/provider/payment/hosting change and before any new production use involving personal or special-category data.