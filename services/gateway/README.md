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

## Endpoints

- `GET /healthz`: Service health check.
- `GET /v1/models`: OpenAI-compatible list of available inference models.
- `POST /v1/chat/completions`: Non-streaming and SSE streaming inference.
- `GET /v1/billing/balance`: Customer current credit balance inquiry.
- `POST /v1/billing/topup`: Automated test balance top-up.

## Test Suite

- `services/gateway/tests/test_gateway_server.py` (6 automated test cases covering authentication, model listings, non-streaming execution, SSE chunk streaming, balance checks, and quota enforcement).
