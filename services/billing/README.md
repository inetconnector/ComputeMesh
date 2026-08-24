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
- Stripe Connect Accounts v2 provider payout onboarding with durable provider accounts, onboarding state, settlement records, transfer idempotency, and ledger payable clearing.
- Stripe webhook event inbox persistence for event-level idempotency and retry visibility, including v1 `account.updated` and Accounts v2 requirement-event Connect status updates.
- Full ledger reconciliation audit verifying zero float drift and zero imbalance across all accounts.

## Units and Precision

- **Base Unit:** Micro-units (`1 CM = 1,000,000 micro-units`, `1 USD = 1,000,000 micro-units`).
- **Precision:** Integer arithmetic exclusively. Floating-point arithmetic is strictly forbidden for balances and ledger postings.
- **Network Fee:** 25.00% (2500 Basis Points) routed to `revenue:network_fee`.
- **Provider Pool:** 75.00% routed proportionally to `provider:{node_id}` payable accounts.

## Key Entry Points

- `Ledger`: Main double-entry journal engine in `services/billing/ledger.py`.
- `AccountingStore`: SQLite operational store for provider accounts, Stripe webhook event inbox state, and settlement records.
- `StripePaymentService`: Creates Stripe Checkout Sessions through the official Stripe SDK and credits deposits only after signed Checkout webhook verification. Purchased compute credits come from Checkout metadata/session reconciliation; tax-inclusive Stripe totals are not treated as extra compute balance.
- `StripeSessionStore`: JSON-backed reconciliation store for Stripe session/customer/payment-intent IDs.
- `StripeConnectService`: Creates Stripe Express recipient connected accounts, onboarding links, and idempotent transfers to connected accounts.
- `SettlementExecutor`: Coordinates Stripe Connect account status refresh, transfers, and internal provider-payable ledger clearing.
- `deposit_customer_credits(...)`: Top-up prepaid balance.
- `record_job_execution(...)`: Debits customer and credits provider(s) + network pool.
- `create_provider_payout(...)`: Internal withdrawal settlement entry for eligible balances after the Stripe Connect transfer path succeeds.
- `reconcile()`: Full audit verifying balance integrity across every account.

## Test Suite

- `services/billing/tests/test_ledger.py` (8 automated test cases covering deposits, proportional splits, duplicate prevention, fail-closed balances, payouts, persistence, and audit reconciliation).
- `services/billing/tests/test_accounting_and_settlement.py` covers durable provider registration, Stripe Connect onboarding links, webhook event inbox idempotency, v1 `account.updated` and Accounts v2 requirement-event Connect status refresh, provider settlement transfer creation, transfer idempotency keys, and ledger payable clearing.
- `services/billing/tests/test_stripe_integration.py` covers fail-closed configuration, Checkout Session parameters, raw signed webhook ingestion, SDK event object normalization, tax-inclusive totals, duplicate webhook idempotency, and signature rejection using an injected test Stripe client.

## Stripe Runtime Configuration

Live Checkout requires:

- `STRIPE_API_KEY`
- `COMPUTEMESH_STRIPE_SESSION_STORE`
- `COMPUTEMESH_ACCOUNT_STORE_PATH`
- Python package `stripe>=15,<16`

Signed ledger crediting from `/v1/billing/webhook` additionally requires `STRIPE_WEBHOOK_SECRET`. The endpoint must receive the exact raw Stripe request body and the `Stripe-Signature` header. Parsed or reformatted JSON is rejected before ledger crediting.

If multiple Stripe event destinations post to the same gateway URL, set `COMPUTEMESH_STRIPE_WEBHOOK_SECRETS` to a comma-separated list of signing secrets. The legacy single `STRIPE_WEBHOOK_SECRET` remains supported.

Stripe Connect provider settlement additionally requires `COMPUTEMESH_ACCOUNT_STORE_PATH` and a Stripe account with Connect enabled. Provider transfers are created with deterministic idempotency keys derived from the ComputeMesh settlement ID; the internal provider payable is cleared only after the Stripe transfer returns an ID.

For current Stripe sandbox accounts, set `COMPUTEMESH_STRIPE_CONNECT_API=v2` so provider onboarding uses the Accounts v2 `/v2/core/accounts` and `/v2/core/account_links` API with `COMPUTEMESH_STRIPE_V2_API_VERSION` defaulting to `2026-07-29.preview`. The v1 SDK path remains only as a compatibility fallback for older Stripe accounts that still permit Accounts v1 creation.

Stripe Connect onboarding cannot be completed with placeholder legal data. For a German UG, finish company formation and registration first, then provide the exact legal company name, commercial-register number, address, representative/KYC data, and payout bank details in Stripe before expecting `payouts_enabled=true`.
