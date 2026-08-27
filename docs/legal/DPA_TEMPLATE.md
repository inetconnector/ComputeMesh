# ComputeMesh Data Processing Agreement (DPA / AVV) — Template

**Draft template for business-customer review. It must be completed with the actual customer, production deployment, subprocessors, locations and processing instructions before signature. It is not automatically effective merely because it is stored in this repository.**

## 1. Parties and subject matter

Controller / Customer: `[legal name, address, contact]`

Processor / Operator: `Herbert Daniel Frede / InetConnector.com, Bismarckstraße 6, 97209 Veitshöchheim, Germany`

Subject matter: processing of personal data contained in customer-submitted inference requests and related service metadata to provide the contracted ComputeMesh inference/orchestration service.

Duration: for the term of the underlying service agreement plus required return/deletion and statutory retention steps.

## 2. Nature and purpose of processing

Depending on the agreed deployment:

- receiving customer API requests;
- transmitting prompts/messages to configured inference runtimes;
- routing portions of workloads to authorized compute providers;
- generating and returning AI output;
- technical metering, execution evidence, security and troubleshooting;
- customer-requested support relating to the processing.

Processing for ComputeMesh's own account administration, fraud/security, billing, legal-compliance or independent purposes may fall outside processor activity and must be described separately in the Privacy Policy and underlying contract.

## 3. Categories of personal data

Customer determines the data submitted. Potential categories can include:

- identifiers/contact information;
- textual business/customer communications;
- application/user content contained in prompts;
- technical/request metadata;
- output that relates to identifiable persons.

**Special-category data under Art. 9 GDPR, criminal-conviction data under Art. 10 GDPR and professional/confidential secrets are not authorized by default.** If a customer requires such processing, it must be separately approved in writing after a deployment/security/DPIA assessment and appropriate safeguards.

## 4. Categories of data subjects

Depending on customer use: customer personnel, the customer's own users/customers, suppliers, business contacts and other persons whose information the customer lawfully includes in submitted content.

## 5. Customer instructions

The Processor processes personal data only on documented instructions of the Customer, including regarding international transfers, unless Union or Member-State law requires otherwise. The API request, configured account/deployment settings, written support instructions and this DPA constitute documented instructions within their agreed scope.

If the Processor believes an instruction infringes data-protection law, it will inform the Customer unless prohibited by law and may suspend the affected processing pending clarification.

## 6. Confidentiality

Persons authorized to process Customer personal data must be bound by confidentiality or an appropriate statutory duty. Access is limited according to role and need.

## 7. Technical and organisational measures

The Processor maintains measures appropriate to risk as described in the current agreed TOM annex. The production-specific TOM annex must be attached or referenced at signature time. Material reductions in agreed security require appropriate notice/handling.

## 8. Subprocessors

The Customer grants `[general / specific — choose one]` authorization for subprocessors listed in the production subprocessor register.

For general authorization, the Processor will provide advance notice of intended additions/replacements and a reasonable opportunity to object on legitimate data-protection grounds. Subprocessors used for processor activity must be bound by data-protection obligations materially equivalent to those required by Art. 28 GDPR.

Independent distributed GPU providers must not be treated casually as mere network peers where they can process Customer personal data. Their legal role, contractual binding, geography, confidentiality and technical access must be determined before they can process Customer personal data under this DPA.

## 9. International transfers

The Processor will not transfer Customer personal data to a third country contrary to Chapter V GDPR. Where required, the parties/subprocessors will use a valid adequacy decision, Standard Contractual Clauses or another lawful mechanism and implement supplementary measures where necessary.

Customer-selected provider/data-residency configurations must remain compatible with these restrictions.

## 10. Assistance with data-subject rights

Taking into account the nature of processing, the Processor will assist the Customer through appropriate technical/organisational measures with requests under Arts. 12–22 GDPR to the extent the relevant data is accessible to the Processor.

If the Processor receives a request relating to Customer-controlled data, it will forward the request to the Customer where legally appropriate and will not independently respond on the Customer's behalf unless instructed or legally required.

## 11. Security and breaches

The Processor will implement Art. 32 measures appropriate to risk and notify the Customer without undue delay after becoming aware of a personal-data breach affecting Customer personal data, providing available information reasonably required for the Customer's Art. 33/34 obligations.

The parties will maintain appropriate incident contacts.

## 12. DPIA and supervisory-authority assistance

Taking into account the nature of processing and information available, the Processor will reasonably assist with DPIAs and prior consultation where required for the Customer's use.

## 13. Deletion or return

At the end of processor services, the Processor will, at the Customer's choice, delete or return Customer personal data and delete existing copies unless Union/Member-State law requires storage. Technical backups may age out under documented backup-retention controls, provided they remain protected and are not restored for ordinary processing after deletion except where necessary for disaster recovery/legal obligations.

Execution/billing/security metadata that the Operator must retain for its own lawful purposes is handled as controller data and is not retained merely under processor instructions; the distinction must be documented.

## 14. Audits and information

The Processor will make available information reasonably necessary to demonstrate compliance with Art. 28 and permit/contribute to audits, including inspections, subject to reasonable confidentiality, security, scope and scheduling protections. Certifications and independent audit reports may be used where appropriate but do not remove statutory rights.

## 15. Liability and main agreement

Liability is governed by applicable law and the negotiated main agreement. Nothing in this DPA excludes mandatory GDPR allocation of responsibility.

## Annex A — Production processing details

Complete before signature:

- Service/deployment name:
- Regions/data residency:
- Approved model/runtime providers:
- Approved distributed compute provider classes:
- Personal-data categories:
- Data-subject categories:
- Special-category processing: `not approved` / `[approved scope]`
- Prompt/output persistence setting:
- Metadata/evidence retention:
- Customer deletion/export mechanism:
- Incident contact Customer:
- Incident contact Processor:

## Annex B — Subprocessors

| Legal entity | Service | Role | Data categories | Processing location(s) | Chapter V mechanism | Contract/TOM status |
| --- | --- | --- | --- | --- | --- | --- |
| Stripe entity applicable to account | Checkout/Connect/payment functions | Determine per activity | payment/KYC/transaction metadata | Complete from production account | Complete before launch | Complete before launch |
| Hosting/CDN/WAF | `[actual provider]` | Determine | infrastructure/log data | `[location]` | `[mechanism]` | `[status]` |
| Distributed compute provider(s) | `[approved provider class/entity]` | Determine before personal-data workloads | workload/derived execution data | `[location]` | `[mechanism]` | `[status]` |

## Annex C — Technical and organisational measures

Attach/reference the production-reviewed version of `docs/legal/TOM.md` plus any deployment-specific control matrix.