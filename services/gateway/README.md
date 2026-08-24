# Gateway Service

**Status:** implemented (Milestone M2 Foundation)

## Purpose

Public OpenAI-compatible API entry point, SSE streaming engine, and credential authentication layer connecting external client SDKs directly to the distributed mesh and double-entry billing ledger.

## Responsibilities

- **API Authentication:** Validates `Authorization: Bearer cm_live_...` credentials and maps to customer ledger accounts.
- **OpenAI Model Catalog:** Serves active models via `/v1/models` in standard OpenAI JSON schema format.
- **Non-Streaming Chat Completions:** Serves `/v1/chat/completions` with full metadata and exact token usage records.
- **Server-Sent Events (SSE) Streaming:** Streams real-time token chunks with `data: {"object": "chat.completion.chunk", ...}` framing and clean `[DONE]` termination.
- **Automated Ledger Integration:** Instantly meters token usage and debits customer deposits while crediting provider payout balances in integer micro-units.
- **Fail-Closed Quota Enforcement:** Rejects requests with HTTP 402 `insufficient_quota` if customer balances are exhausted.
- **Stripe Checkout:** Creates real Stripe Checkout Sessions when `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, and `COMPUTEMESH_STRIPE_SESSION_STORE` are configured.
- **Signed Webhook Ingestion:** Credits customer balances only from raw Stripe webhook payloads that verify against the `Stripe-Signature` header.

## Endpoints

- `GET /healthz`: Service health check.
- `GET /v1/models`: OpenAI-compatible list of available inference models.
- `POST /v1/chat/completions`: Non-streaming and SSE streaming inference.
- `GET /v1/billing/balance`: Customer current credit balance inquiry.
- `POST /v1/billing/checkout`: Create a Stripe Checkout Session for prepaid compute credits.
- `POST /v1/billing/webhook`: Stripe webhook endpoint. Requires raw body plus `Stripe-Signature`.
- `POST /v1/billing/topup`: Test/admin balance top-up. Normal bearer tokens cannot self-credit unless `COMPUTEMESH_ALLOW_TEST_TOPUP=1` is deliberately set for local testing.

## Stripe Runtime Configuration

Install the runtime dependency with `python -m pip install -r requirements.txt` and configure:

- `STRIPE_API_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `COMPUTEMESH_STRIPE_SESSION_STORE`
- optional `COMPUTEMESH_GATEWAY_LEDGER_PATH` for durable gateway ledger storage

If `STRIPE_API_KEY` is present but the SDK, webhook secret, or session store is missing, startup/checkout fails closed instead of issuing fake payment URLs.

## Test Suite

- `services/gateway/tests/test_gateway_server.py` covers authentication, model listings, non-streaming execution, SSE chunk streaming, balance checks, quota enforcement, Stripe Checkout wiring, signed webhook crediting, and missing-signature rejection.
