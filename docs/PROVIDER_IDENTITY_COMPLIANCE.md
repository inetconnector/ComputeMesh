# ComputeMesh Provider Identity & Multi-Tier EU Digital Regulation Compliance

## 1. Executive Summary & Core Architectural Principle

ComputeMesh implements a robust, privacy-preserving, and legally grounded identity and governance architecture for fleet operators and compute providers. 

The architecture strictly separates platform domain identity from payment regulatory KYC and evaluates digital regulation compliance dynamically according to the concrete product and transaction context.

```text
┌────────────────────────────────────────────────────────┐
│ ComputeMesh Account (facc_...)                         │
│ User Login / Passkeys / WebAuthn Authentication        │
└───────────────────────────┬────────────────────────────┘
                            │ 1 : 1
                            ▼
┌────────────────────────────────────────────────────────┐
│ Provider Identity (prv_...)                            │
│ Legal Identity & Verification Domain (General Platform)│
│ - Natural Person (Individual) vs Business Entity       │
│ - Structured Address (ISO 3166-1 alpha-2)              │
│ - Commercial / Business Registry Reference             │
│ - Field-Level Verification Evidence                    │
└─────────────┬───────────────────────────┬──────────────┘
              │                           │
              ▼                           ▼
┌───────────────────────────┐ ┌──────────────────────────┐
│ Stripe Connect (PSP)      │ │ DSA Applicability Policy │
│ Payment & Payout Gateway  │ │ Dynamic Scope Evaluation │
│ - Bank accounts & IBANs   │ │ - Mode: Intermediary/B2B │
│ - Regulated AML / KYC     │ │ - Reseller vs Private    │
│ - Payment processing      │ │ - Art. 29 SME Exemption  │
└───────────────────────────┘ └───────────┬──────────────┘
                                          │
              ┌───────────────────────────┴──────────────┐
              │                                          │
              ▼ (1 : N)                                  ▼
┌───────────────────────────┐               ┌──────────────────────────┐
│ Fleet A, B, C             │               │ Public Transparency DTO  │
│ ControlPlane Governance   │               │ - MinimalProviderProfile │
│ - Hardware Attestation    │               │ - DSAArt30Disclosure     │
│ - Scheduling (Zero PII)   │               │   (Only when applicable) │
└───────────────────────────┘               └──────────────────────────┘
```

---

## 2. Product, Marketplace & Contract Counterparty Models

Compliance obligations (particularly under the Digital Services Act) depend strictly on the contractual and operational relationship between the parties. ComputeMesh distinguishes between four distinct marketplace modes:

| Marketplace Mode | Counterparty Model | Customer Audience | DSA Art. 30 Applicability | Primary Legal Basis |
| :--- | :--- | :--- | :--- | :--- |
| **`PUBLIC_INTERMEDIARY`** | Customer ↔ Provider | `CONSUMER_ALLOWED` | **Applicable** (unless Art. 29 SME applies) | DSA Art. 30(1), Art. 31 |
| **`PUBLIC_RESELLER`** | Customer ↔ ComputeMesh | `CONSUMER_ALLOWED` | **Exempt** (Customer contracts with platform) | DSA Art. 30(1) |
| **`B2B_INTERMEDIARY`** | Business ↔ Provider | `BUSINESS_ONLY` | **Exempt** (No consumer distance contracts) | DSA Art. 30(1), GDPR Art. 6(1)(b) |
| **`PRIVATE_CLUSTER`** | Direct Private Member | `PRIVATE_MEMBERS` | **Exempt** (Closed infrastructure, no public offer) | DSA Art. 3(i), GDPR Art. 6(1)(b) |
| **`ENTERPRISE_PRIVATE`** | Direct Private Member | `PRIVATE_MEMBERS` | **Exempt** (Dedicated internal capacity) | DSA Art. 3(i), GDPR Art. 6(1)(b) |

---

## 3. Digital Services Act (Regulation (EU) 2022/2065) Evaluation

### A. Article 29: Micro and Small Enterprise Operator Exemption
Under **DSA Article 29(1)**, online platforms that qualify as micro or small enterprises within the meaning of **Recommendation 2003/361/EC** (< 50 staff, annual turnover or balance sheet total ≤ EUR 10 million) are **exempt** from the obligations of Chapter III Section 3, including:
- Article 30 (Traceability of Traders)
- Article 31 (Compliance by Design)

ComputeMesh models this via `PlatformOperatorLegalProfile`:
- If `enterprise_size` is `MICRO_ENTERPRISE` or `SMALL_ENTERPRISE`, Article 30 is legally not enforced.
- If `enterprise_size` is `UNKNOWN`, the system triggers `LEGAL_REVIEW_REQUIRED` / `APPLICABILITY_UNKNOWN` and avoids unlawful over-collection of personal data.

### B. Article 30: Traceability of Traders
When Article 30 applies (e.g. non-exempt platform operating a public consumer marketplace):
1. **Required Information (Art. 30(1)):** Name, address, email, phone number, copy of identification or other electronic identification, payment account details, commercial register name and registration number, and self-certification (Art. 30(1)(e)).
2. **Best-Effort Verification (Art. 30(2)):** Verified using official online databases (commercial registers, VIES) or trustworthy electronic identification.
3. **Storage Limitation (Art. 30(5)):** Traceability records must be stored for **at most 6 months** after the contractual relationship with the trader has ended, and thereafter erased.
4. **Online Interface Transparency (Art. 30(7)):** The platform must publish on its online interface the trader's name, address, phone number, email, and commercial register details in a clear and easily accessible manner.

---

## 4. GDPR (Regulation (EU) 2016/679) & Data Inventory Matrix

Each personal data field is processed under a documented lawful basis pursuant to GDPR Article 6(1):

| Field | Purpose | Legal Basis (Public Intermediary) | Legal Basis (B2B / Private Cluster) | Visibility | Retention Rule |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `legal_name` | Identity & contract execution | Art. 6(1)(c) GDPR (DSA Art. 30) | Art. 6(1)(b) GDPR (Contract) | Public (Trade name or Legal name) | Contract + 6 mo (DSA) / Commercial law |
| `address` (`line1`, `postal_code`, `city`, `country_code`) | Serviceable business address | Art. 6(1)(c) GDPR (DSA Art. 30) | Art. 6(1)(b) GDPR (Billing/Tax routing) | Natural Person: City/Postal public; Line1 protected.<br>Business: Public | Contract + 6 mo (DSA) / Commercial law |
| `email` | Operational contact & notices | Art. 6(1)(c) GDPR (DSA Art. 30) | Art. 6(1)(b) GDPR (Contract) | Public | Contract + 6 mo |
| `phone` | Direct contact channel | Art. 6(1)(c) GDPR (DSA Art. 30) | Art. 6(1)(b) GDPR (Optional) | Business: Public.<br>Natural Person: Private unless explicitly designated | Contract + 6 mo |
| `registry_info` | Entity verification | Art. 6(1)(c) GDPR (DSA Art. 30) | Art. 6(1)(b) GDPR (Business verification) | Public | Contract + 6 mo |
| `vat_id` | Tax compliance | Art. 6(1)(c) GDPR (Fiscal obligations) | Art. 6(1)(c) GDPR (Tax law) | Public if applicable | Statutory fiscal (10 yrs) |
| `stripe_account_id` | Payout routing reference | Art. 6(1)(b) GDPR (Payment execution) | Art. 6(1)(b) GDPR (Payment execution) | **Strictly Private** | Managed by Stripe / PSP |
| `prompt_stream_data` | AI token generation | Art. 6(1)(b) GDPR | Art. 6(1)(b) GDPR | In-Memory Volatile RAM only | **Zero-Disk Retention** (Purged immediately) |

---

## 5. Stripe Connect & Financial AML/KYC Boundaries

- **Stripe is the regulated Payment Service Provider (PSP)** responsible for financial AML/KYC, customer bank verification, sanctions screening, and payout processing.
- ComputeMesh **does not store** bank account numbers, IBANs, passports, ID document scans, or biometric data.
- Stripe payout verification status is received via signed webhooks and stored as an `IdentityEvidence` record (`source = STRIPE_CONNECT`, `field_scope = payout_account`).
- A verified Stripe account indicates payout readiness, but is evaluated independently from platform trader traceability.

---

## 6. DAC7 (Directive (EU) 2021/514) Product Scope Trigger

- **Current Scope Evaluation:** ComputeMesh provides automated computational GPU/CPU capacity. Under current EU DAC7 rules, pure automated compute capacity provisioning does not constitute a "Relevant Activity" (which covers sale of goods, personal services, rental of immovable property, or rental of transport).
- **Dynamic Scope Trigger:** If ComputeMesh introduces human consulting, manual data annotation, or personal services in the future, DAC7 reporting triggers will be activated accordingly.

---

## 7. Category-Based Retention Engine

Retention rules are managed by `RetentionEngine` ([retention_policy.py](file:///c:/Users/frede/Projekte/ComputeMesh-ControlPlane/ComputeMesh/services/compliance/retention_policy.py)):

1. **`PROMPT_INFERENCE_DATA`**: 0 days duration (`PURGE_IMMEDIATELY`). Zero-disk retention in volatile RAM.
2. **`DSA_TRADER_RECORDS`**: 180 days (6 months) post-contract termination under DSA Art. 30(5), then deleted.
3. **`INACTIVE_DRAFT_PROFILES`**: 90 days after creation if incomplete with no bound fleets, then deleted.
4. **`SECURITY_AUDIT_LOGS`**: 365 days after event, then account identifiers are anonymized.
5. **`ACCOUNTING_TAX_RECORDS`**: 10 years statutory fiscal retention under applicable commercial law.

---

## 8. Dynamic Public Disclosure

Public profiles are strictly allowlisted via dedicated DTOs:
- **`MinimalProviderPublicProfile`**: Exposes only `provider_identity_id`, `trade_or_legal_name`, `country_code`, and `verification_status`. Natural person residential addresses and phone numbers are completely shielded.
- **`DSAArticle30PublicDisclosure`**: Generated **only** when `DSAApplicabilityPolicy` determines that Article 30 is legally applicable. Contains public trader disclosures mandated by Art. 30(7).
