# Billing and Ledger Service

**Status:** implemented (M2 Foundation)

## Purpose

Convert accepted metering evidence into immutable, auditable customer debits and provider payable credits using double-entry bookkeeping with integer micro-unit precision.

## Responsibilities

- Dynamic pricing catalog evaluation per model tier (0.5B, 7B, 14B, 32B, 70B).
- Idempotent metering event acceptance with unique event hash deduplication.
- Append-only double-entry journal with strict invariant $\sum \text{debits} = \sum \text{credits}$.
- Multi-provider proportional reward allocation for distributed pipeline execution.
- Minimum payout threshold accounting ($25.00 / 25,000,000 micro-units) and settlement summary export.
- Customer compute-credit purchases are processed through the Stripe-backed Checkout/Webhook integration when live Stripe environment values are configured; wallet addresses are provider payout destinations only.
- Full ledger reconciliation audit verifying zero float drift and zero imbalance across all accounts.

## Units and Precision

- **Base Unit:** Micro-units (`1 CM = 1,000,000 micro-units`, `1 USD = 1,000,000 micro-units`).
- **Precision:** Integer arithmetic exclusively. Floating-point arithmetic is strictly forbidden for balances and ledger postings.
- **Network Fee:** 25.00% (2500 Basis Points) routed to `revenue:network_fee`.
- **Provider Pool:** 75.00% routed proportionally to `provider:{node_id}` payable accounts.

## Key Entry Points

- `Ledger`: Main double-entry journal engine in `services/billing/ledger.py`.
- `StripePaymentService`: Creates Stripe Checkout Sessions through the official Stripe SDK and credits deposits only after signed Checkout webhook verification.
- `StripeSessionStore`: JSON-backed reconciliation store for Stripe session/customer/payment-intent IDs.
- `deposit_customer_credits(...)`: Top-up prepaid balance.
- `record_job_execution(...)`: Debits customer and credits provider(s) + network pool.
- `create_provider_payout(...)`: Internal withdrawal settlement summary for eligible balances. A separate Stripe/settlement executor is required for real payouts.
- `reconcile()`: Full audit verifying balance integrity across every account.

## Test Suite

- `services/billing/tests/test_ledger.py` (8 automated test cases covering deposits, proportional splits, duplicate prevention, fail-closed balances, payouts, persistence, and audit reconciliation).
- `services/billing/tests/test_stripe_integration.py` covers fail-closed configuration, Checkout Session parameters, raw signed webhook ingestion, duplicate webhook idempotency, and signature rejection using an injected test Stripe client.

## Stripe Runtime Configuration

Live Checkout requires:

- `STRIPE_API_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `COMPUTEMESH_STRIPE_SESSION_STORE`
- Python package `stripe>=15,<16`

`/v1/billing/webhook` must receive the exact raw Stripe request body and the `Stripe-Signature` header. Parsed or reformatted JSON is rejected before ledger crediting.
