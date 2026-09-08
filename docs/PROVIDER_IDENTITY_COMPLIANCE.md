# ComputeMesh Provider & Trader Identity Compliance

This document specifies the privacy-preserving, EU-compliant identity and operator verification layer for the **ComputeMesh Fleet Management & Marketplace**.

---

## 1. Domain Separation & Architecture

ComputeMesh strictly separates five distinct functional layers:

```text
┌─────────────────────────────────────────────────────────────┐
│ 1. ComputeMesh Account                                       │
│ Login, WebAuthn Passkeys, Magic-Link (facc_...)             │
│ Authenticates the natural person / operator logging in      │
└──────────────────────────────┬──────────────────────────────┘
                               │ operates on behalf of
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. ComputeMesh Provider / Trader Identity                    │
│ - Natural Person (Individual) or Legal Entity (Business)    │
│ - Structured serviceable address (ISO 3166-1 alpha-2)       │
│ - Commercial register info & registration number             │
│ - Field-Level Verification Evidence (IdentityEvidence)      │
│ - Versioned DSA Art. 30 Trader Self-Declaration              │
│ - Strict PublicTraderProfile allowlist (Zero PII leakage)   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                │ owns (1 Provider : N Fleets)│ payout status / references only
                ▼                             ▼
┌───────────────────────────────┐ ┌───────────────────────────┐
│ 3. Fleet(s)                   │ │ 4. Stripe Connect         │
│ - Operational compute units   │ │ - Payouts & Payments      │
│ - Server-Side Marketplace Gate│ │ - Financial KYC / AML     │
│ - Legacy Migration Support    │ │   managed by Stripe       │
└───────────────┬───────────────┘ └───────────────────────────┘
                │ minimal status sync (fleet_id, compliance_state)
                ▼
┌───────────────────────────────┐
│ 5. ControlPlane Governance    │
│ - Fleet Policies & Placement  │
│ - Zero raw PII in ControlPlane│
└───────────────────────────────┘
```

> [!IMPORTANT]
> **Stripe Separation:** Stripe is responsible for payment processing, payouts, and financial regulatory KYC/AML. ComputeMesh does **not** duplicate an AML/Payment-KYC system. ComputeMesh manages provider traceability and operator accountability under European digital platform law.

---

## 2. Legal Analysis & Assumptions

### A. Regulation (EU) 2022/2065 – Digital Services Act (DSA)
- **Art. 30 (Traceability of Traders):** Platforms enabling distance contracts between traders and consumers/businesses must obtain and verify key trader details (name, address, email, telephone, company register, registration number, and self-certification) before allowing marketplace activities.
- **Art. 31 (Compliance by Design):** Interfaces are structured to allow traders to provide and maintain required information and declarations seamlessly.

### B. Regulation (EU) 2016/679 – General Data Protection Regulation (GDPR)
- **Art. 5 (Principles):** Data minimization, purpose limitation, storage limitation, integrity, and confidentiality.
- **Art. 6 (Lawfulness):**
  - Art. 6(1)(c) GDPR: Legal obligation under DSA Art. 30 for mandatory provider transparency.
  - Art. 6(1)(b) GDPR: Performance of contract for fleet account management and payouts.
  - Art. 6(1)(f) GDPR: Legitimate interest in preventing fraud, abuse, and platform manipulation.
- **Art. 25 (Data Protection by Design & by Default):** Public endpoints expose only filtered `PublicTraderProfile` allowlists. Raw sensitive documents (ID scans, selfies, residential addresses of company representatives) are strictly not collected or stored.

### C. Regulation (EU) 2019/1150 – Platform-to-Business (P2B) Regulation
- Requires transparent, reasoned communication for any restriction, suspension, or termination of business provider services.

### D. Directive (EU) 2021/514 – DAC7 Evaluation
- **Scope Analysis:** ComputeMesh provides decentralized automated compute infrastructure capacity. Pure IT compute capacity leasing does not constitute a relevant activity under DAC7 (which covers sale of goods, rental of real estate, personal services, or rental of transport). No redundant tax reporting fields are unnecessarily forced on users.

---

## 3. Data Inventory Matrix

| Field | Purpose | Legal Basis | Role | Source | Verification Method | Public / Private | Retention Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `provider_identity_id` | Domain identifier | Art. 6(1)(b) GDPR | All | System | Generated | Public | Active + 5 yrs statutory |
| `entity_type` | Individual vs Business | Art. 6(1)(c) GDPR (DSA Art. 30) | Provider | User | Self-attestation | Public | Active + 5 yrs statutory |
| `legal_name` | Legal name of trader/entity | Art. 6(1)(c) GDPR (DSA Art. 30) | Provider | User / Register | Register / Review | Public | Active + 5 yrs statutory |
| `trade_name` | Public business name | Art. 6(1)(b) GDPR | Business | User | User | Public | Active + 5 yrs statutory |
| `legal_representative` | Authorized officer (GmbH GF) | Art. 6(1)(c) GDPR | Business | User | Register | Private | Active + 5 yrs statutory |
| `acting_person_relationship` | Connection to business | Art. 6(1)(f) GDPR | Business | User | Self-attestation | Private | Active + 5 yrs statutory |
| `address` (`line1`, `line2`, `postal_code`, `city`, `state`, `country_code`) | Serviceable address | Art. 6(1)(c) GDPR (DSA Art. 30) | Provider | User | Register / Review | Partial (City/Postal/Country public) | Active + 5 yrs statutory |
| `email` | Official business contact | Art. 6(1)(c) GDPR (DSA Art. 30) | Provider | User | Account verification | Public | Active + 5 yrs statutory |
| `phone` | Direct contact channel | Art. 6(1)(c) GDPR (DSA Art. 30) | Provider | User | User attestation | Private | Active + 5 yrs statutory |
| `registry_info` (`country`, `name`, `number`) | Company registration | Art. 6(1)(c) GDPR (DSA Art. 30) | Business | User | Register check | Public | Active + 5 yrs statutory |
| `vat_id` | Tax identifier | Art. 6(1)(c) GDPR | If applicable | User | VIES / Self | Public | Active + 5 yrs statutory |
| `stripe_account_id` | Stripe Connected Account | Art. 6(1)(b) GDPR | Payout recipient | Stripe Connect | Stripe OAuth / Webhook | Private | Active account duration |
| `trader_declaration` (`version`, `accepted_at`, `locale`, `ip_hash`) | DSA Art. 30 Self-Declaration | Art. 6(1)(c) GDPR (DSA Art. 30) | Marketplace Provider | User | Cryptographic record | Private (status public) | 5 yrs after termination |

---

## 4. REST API Contract

### Provider Profile & Compliance
- `GET /api/portal/fleet/provider-identity`: Returns the authenticated account's `PrivateComplianceView`, including field statuses, missing requirements, and active declarations.
- `POST /api/portal/fleet/provider-identity`: Creates or updates the provider profile. If a `VERIFIED` profile modifies material fields (legal name, entity type, country, address, or registry number), it automatically transitions to `REVERIFICATION_REQUIRED`.
- `POST /api/portal/fleet/provider-identity/declaration`: Records an accepted versioned DSA Art. 30 self-declaration (`dsa_art30_v1.0`).

### Public Marketplace Transparency
- `GET /api/traders/{provider_identity_id}/public`: Returns `PublicTraderProfile` containing only the legally required public transparency disclosure.

---

## 5. Migration Strategy for Existing Fleets

1. Existing fleets created before identity enforcement are classified as `LEGACY_UNVERIFIED`.
2. Hardware bindings and existing credits are preserved without disruption.
3. Operators are prompted in the cockpit to complete their provider profile and DSA Art. 30 declaration.
4. Upon completing verification, fleets transition to `ACTIVE` marketplace state.
