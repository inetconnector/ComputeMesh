# ComputeMesh GDPR Incident, Breach and DPIA Procedure

## Personal-data incident workflow

1. **Detect and contain.** Isolate affected credentials, provider sessions, hosts, storage or network paths without destroying evidence.
2. **Open an incident record.** Record discovery time, reporter, affected services, suspected data categories, systems/providers and containment steps.
3. **Determine roles.** For each affected dataset determine whether InetConnector is controller, processor, or another recipient. Do not assume one role applies to every data flow.
4. **Assess the breach.** Determine whether there was accidental/unlawful destruction, loss, alteration, unauthorized disclosure of or access to personal data.
5. **Assess risk to persons.** Consider data sensitivity, identifiability, volume, encryption/key compromise, ability to misuse data, affected individuals and likely consequences.
6. **Processor notification.** Where InetConnector acts as processor, notify the relevant controller without undue delay and provide available facts needed for its GDPR obligations.
7. **Supervisory-authority assessment.** Where InetConnector is controller, assess Art. 33 GDPR notification and document the reason whether notification is or is not required. If notification is required, the statutory 72-hour framework must be managed from awareness, with supplemental information provided as permitted.
8. **Data-subject notification assessment.** Assess Art. 34 GDPR where the breach is likely to result in a high risk to individuals, subject to statutory exceptions.
9. **Subprocessor/provider coordination.** Preserve logs/evidence, obtain incident facts, stop further exposure and ensure contractual notification duties are followed.
10. **Remediate and review.** Rotate keys, patch vulnerabilities, correct access/retention controls, test fixes and update TOMs/threat/privacy documents.

No incident handler may conceal or delay a legally required notification merely to protect reputation.

## Minimum incident record

- unique incident ID;
- date/time discovered and date/time awareness threshold assessed;
- affected controller/customer(s);
- affected systems, regions and processors/providers;
- categories/approximate number of data subjects and records where known;
- data categories and whether encrypted/pseudonymized;
- credential/key compromise status;
- likely consequences;
- containment/remediation;
- notification decisions and reasoning;
- communications sent;
- final lessons/actions and owners.

## DPIA / DSFA screening

Perform and record DPIA screening before introducing or materially changing processing that can plausibly create high risk, including:

- systematic use of AI output for decisions with significant effects on individuals;
- large-scale/sensitive or special-category data;
- systematic monitoring/profiling;
- large-scale distributed processing where independent provider machines can receive identifiable workload content;
- new combinations of datasets or novel technology that materially increase privacy/security risk;
- vulnerable data subjects;
- broad third-country provider routing without strong residency controls.

### Screening questions

- What exact purpose requires personal data?
- Can the purpose be achieved with less/no personal data?
- Who is controller/processor for each processing stage?
- Which providers/subprocessors receive the data and where?
- Can raw content be replaced with digests/pseudonyms?
- What is the necessity and proportionality of retention?
- What failures/misuse could harm individuals?
- What security, access, geography and contractual controls reduce the risk?
- Does residual risk remain high after controls?

If processing is likely to result in high risk, complete a formal Art. 35 DPIA before production. If high residual risk remains despite measures, assess prior consultation under Art. 36 GDPR.

## Production owner

A named person must own privacy incident response, DPA/subprocessor records, DPIA screening and periodic compliance review. A generic mailbox alone is not an operational procedure.