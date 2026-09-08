# ComputeMesh Pre-Launch Legal & Regulatory Review Checklist

This checklist outlines the key corporate, contractual, and regulatory determinations to be finalized by qualified platform legal counsel prior to commercial production launch.

---

## 1. Platform Operator Entity & DSA Article 29 Sizing
- [ ] **Corporate Headcount & Financial Metrics:** Confirm whether the platform operating entity qualifies as a Micro or Small Enterprise under EC Recommendation 2003/361/EC (< 50 employees, annual turnover or balance sheet total ≤ EUR 10m).
- [ ] **Environment Configuration:** Set `COMPUTEMESH_OPERATOR_ENTERPRISE_SIZE` in deployment manifests (`MICRO_ENTERPRISE`, `SMALL_ENTERPRISE`, or `NOT_SMALL_ENTERPRISE`).
- [ ] **Applicability Confirmation:** Verify that if the SME exemption applies, Chapter III Section 3 (DSA Art. 30/31) obligations are waived.

---

## 2. Marketplace & Contract Counterparty Model
- [ ] **Intermediary vs. Reseller Model:** Determine the formal commercial terms:
  - *Model A (Intermediary):* Customer concludes contract directly with the compute provider.
  - *Model B (Reseller):* Customer concludes contract with ComputeMesh; compute provider acts as upstream infrastructure subcontractor.
- [ ] **Customer Onboarding Restrictions:** Confirm whether the marketplace permits consumers (B2C) or is strictly restricted to verified businesses (B2B). If B2B-only, ensure terms explicitly prohibit consumer accounts.

---

## 3. Terms of Service & Legal Declarations
- [ ] **Platform Terms of Service (v2.1):** Finalize platform terms, service level agreements (SLAs), and operational rules.
- [ ] **Provider Agreement:** Ensure terms clearly state fleet operator responsibilities, hardware availability standards, and suspension protocols (P2B Regulation Art. 3 & 4).
- [ ] **Trader Self-Certification (`DSA_ART30_TRADER_COMMITMENT`):** Review the legal text version for statutory compliance with DSA Art. 30(1)(e).
- [ ] **Data Processing Agreement (DPA):** Review GDPR Art. 28 processor terms for business customer data streaming.

---

## 4. Privacy, GDPR & Public Disclosure
- [ ] **Privacy Policy:** Verify privacy disclosures detailing lawful bases under GDPR Art. 6(1)(b), (c), and (f).
- [ ] **Natural Person Trader Disclosure:** Confirm that individual provider home addresses and private phone numbers are shielded unless legally mandated by Art. 30(7) in an applicable B2C marketplace.
- [ ] **Statutory Retention Rules:** Confirm statutory commercial/tax retention periods in the operator's jurisdiction.

---

## 5. Stripe Connect & Financial Regulatory Compliance
- [ ] **PSP Agreement:** Finalize Stripe Connect platform terms (Custom vs. Express onboarding).
- [ ] **Chargeback & Settlement Terms:** Review payment dispute and payout reserve policies.
- [ ] **Tax & Invoicing:** Verify whether ComputeMesh or the provider is responsible for issuing VAT invoices to end customers.

---

## 6. DAC7 & Future Scope Triggers
- [ ] **Compute Infrastructure Scope:** Confirm that automated GPU/CPU compute leasing remains outside DAC7 reportable activities.
- [ ] **Product Evolution Monitoring:** Establish an operational review process if human-assisted services (ML consulting, managed AI operators) are introduced.
