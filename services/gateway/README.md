# Gateway Service

**Status:** implemented (Milestone M2 Foundation)

## Purpose

Public OpenAI-compatible and Ollama-compatible API entry point, SSE/NDJSON streaming engine, and credential authentication layer connecting external client SDKs directly to the distributed mesh and double-entry billing ledger.

## Responsibilities

- **API Authentication:** Validates registered `Authorization: Bearer cm_live_...` and `cm_provider_...` credentials and maps them to ledger accounts. Unknown live/provider tokens fail closed unless an explicit lab compatibility flag is enabled.
- **OpenAI Model Catalog:** Serves active models via `/v1/models` in standard OpenAI JSON schema format.
- **Ollama Model Catalog:** Serves the same active models via `/api/tags` in Ollama-compatible JSON schema format.
- **Non-Streaming Chat Completions:** Serves `/v1/chat/completions` with full metadata and runtime-reported token usage records.
- **Ollama Chat/Generate Facade:** Serves `/api/chat` and `/api/generate` with Ollama-compatible JSON/NDJSON response shapes while using the same authentication, ledger metering and provider attribution as OpenAI requests.
- **Server-Sent Events (SSE) Streaming:** Streams response chunks with `data: {"object": "chat.completion.chunk", ...}` framing and clean `[DONE]` termination.
- **Web Teaser Demo:** Allows unauthenticated browser/OpenAI/Ollama demo requests for a limited rolling window and can forward to a private OpenAI- or Ollama-compatible runtime backend when configured.
- **Automated Ledger Integration:** Meters successful inference usage and debits customer deposits while crediting provider payout balances in integer micro-units.
- **Fail-Closed Runtime Configuration:** Production inference returns service-unavailable rather than fabricating completion output when no runtime backend is configured.
- **Fail-Closed Quota Enforcement:** Rejects requests with HTTP 402 `insufficient_quota` if customer balances are exhausted.
- **Stripe Checkout:** Creates real Stripe Checkout Sessions when `STRIPE_API_KEY` and `COMPUTEMESH_STRIPE_SESSION_STORE` are configured.
- **Signed Webhook Ingestion:** Credits customer balances only from raw Stripe webhook payloads that verify against the `Stripe-Signature` header, normalizing Stripe SDK event objects before ledger processing.
- **Stripe Connect Provider Settlement:** Registers Stripe Accounts v2 Express recipient payout accounts, creates onboarding links, and lets admins run idempotent provider settlements that transfer funds before clearing provider payables in the ledger.

## Endpoints

- `GET /healthz`: Service health check.
- `GET /v1/models`: OpenAI-compatible list of available inference models.
- `POST /v1/chat/completions`: Non-streaming and SSE streaming inference.
- `GET /api/tags`: Ollama-compatible list of available inference models.
- `POST /api/chat`: Ollama-compatible chat inference. Supports non-streaming JSON and streaming NDJSON.
- `POST /api/generate`: Ollama-compatible prompt inference. Supports non-streaming JSON and streaming NDJSON.
- `GET /v1/billing/balance`: Customer current credit balance inquiry.
- `POST /v1/billing/checkout`: Create a Stripe Checkout Session for prepaid compute credits.
- `POST /v1/billing/webhook`: Stripe webhook endpoint. Requires raw body plus `Stripe-Signature`.
- `POST /v1/billing/topup`: Test/admin balance top-up. Normal bearer tokens cannot self-credit unless `COMPUTEMESH_ALLOW_TEST_TOPUP=1` is deliberately set for local testing.
- `POST /v1/providers/register`: Provider-authenticated registration/update for payout metadata.
- `POST /v1/providers/stripe/onboarding`: Provider-authenticated Stripe Connect account creation/refresh plus onboarding link generation.
- `POST /v1/providers/stripe/refresh`: Provider-authenticated Stripe Connect account status refresh after onboarding.
- `GET /v1/providers/status`: Provider-authenticated account and payable-balance status.
- `GET /v1/admin/providers`: Admin-only provider account and payable-balance listing.
- `GET /v1/admin/settlements`: Admin-only settlement record listing with optional `status` and `limit` query parameters.
- `POST /v1/admin/settlements/provider`: Admin-only provider settlement execution through Stripe Connect. Settlement records include the Stripe Transfer currency.

## Inference Runtime Configuration

The gateway no longer treats an internally generated string as successful inference. With no backend configured it fails closed. For an OpenAI-compatible runtime such as a suitably configured `llama-server`, set:

```text
COMPUTEMESH_INFERENCE_BACKEND=openai_compatible
COMPUTEMESH_INFERENCE_URL=http://127.0.0.1:8080
COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS=120
```

`COMPUTEMESH_INFERENCE_API_KEY` is optional for a protected compatible endpoint. The runtime response must contain `choices[0].message.content` and integer `usage.prompt_tokens` / `usage.completion_tokens`; malformed responses are rejected and are not billed.

For an Ollama-backed public demo on a private local daemon, set:

```text
COMPUTEMESH_INFERENCE_BACKEND=ollama
COMPUTEMESH_INFERENCE_URL=http://127.0.0.1:11434
COMPUTEMESH_INFERENCE_MODEL=qwen2.5:1.5b-instruct
COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS=60
COMPUTEMESH_INFERENCE_MAX_PREDICT=48
COMPUTEMESH_INFERENCE_CONTEXT_TOKENS=128
COMPUTEMESH_INFERENCE_THREADS=2
COMPUTEMESH_INFERENCE_SYSTEM_PROMPT=You are the ComputeMesh demo assistant. Explain that ComputeMesh is a decentralized AI inference network and answer concisely.
```

`COMPUTEMESH_INFERENCE_MODEL` is optional; when set, it maps public catalog aliases to the concrete locally installed runtime model.

Synthetic completion is retained only as an explicit test/development fixture and requires both:

```text
COMPUTEMESH_INFERENCE_BACKEND=synthetic
COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE=1
```

This gateway backend is a real runtime bridge, not yet the final scheduler/orchestrator integration. The next step is for the orchestrator to dispatch a reserved planner-selected multi-node execution and expose that execution through the same backend contract.

## Stripe Runtime Configuration

Install the runtime dependency with `python -m pip install -r requirements.txt` and configure:

- `STRIPE_API_KEY`
- `COMPUTEMESH_STRIPE_SESSION_STORE`
- `STRIPE_WEBHOOK_SECRET` for signed webhook crediting
- optional `COMPUTEMESH_STRIPE_WEBHOOK_SECRETS` as a comma-separated list when multiple Stripe event destinations post to the same webhook URL
- optional `COMPUTEMESH_GATEWAY_LEDGER_PATH` for durable gateway ledger storage
- optional `COMPUTEMESH_ACCOUNT_STORE_PATH` for durable provider accounts, webhook event inbox state, and settlement records
- optional `COMPUTEMESH_STRIPE_CONNECT_API=v2` for Stripe Accounts v2 provider onboarding
- optional `COMPUTEMESH_STRIPE_V2_API_VERSION` for the Stripe Accounts v2 preview API version, defaulting to `2026-07-29.preview`
- optional `COMPUTEMESH_STRIPE_SETTLEMENT_CURRENCY`, defaulting to `usd`, for Stripe Connect Transfers when the platform Stripe balance settles in another currency such as `eur`
- optional `COMPUTEMESH_PROVIDER_SHARES` as `provider_id:ratio,provider_id:ratio` for operator-controlled metering attribution before the scheduler supplies runtime provider shares
- optional `COMPUTEMESH_DEFAULT_PROVIDER_NODE_ID`, defaulting to `lab-mesh-default-rig`, when no provider-share list is configured
- optional `COMPUTEMESH_API_KEY_STORE_PATH` for the shared Portal/Gateway JSON key registry written by `/api/v1/register`
- optional `COMPUTEMESH_API_KEYS` as comma-separated `token:account_id` static registrations for operator-managed keys
- required `COMPUTEMESH_ADMIN_KEY` for admin endpoints; there is no built-in default admin credential
- optional lab-only `COMPUTEMESH_ALLOW_DYNAMIC_CUSTOMER_KEYS=1` and `COMPUTEMESH_ALLOW_DYNAMIC_PROVIDER_TOKENS=1` for private throwaway testing only
- optional `COMPUTEMESH_TEASER_WINDOW_SECONDS`, defaulting to `14400`, for automatic unauthenticated demo quota reset
- optional `COMPUTEMESH_INFERENCE_MODEL` for mapping public catalog IDs to a concrete local runtime model such as an Ollama tag

If `STRIPE_API_KEY` is present but the SDK or session store is missing, startup/checkout fails closed instead of issuing fake payment URLs. Webhook crediting remains fail-closed until `STRIPE_WEBHOOK_SECRET` is configured.

Stripe Checkout tax totals are handled as payment/tax settlement data, not extra customer compute credit. The ledger credits the purchased compute-credit amount recorded in Checkout metadata and the durable session store.

Stripe Connect settlement fails closed until the account store is configured, Stripe Connect can create/retrieve connected accounts, provider onboarding is complete enough for payouts, and the provider payable balance exceeds the minimum payout threshold. The Stripe webhook path accepts v1 `account.updated` and Accounts v2 `v2.core.account...` requirement events to keep provider Connect readiness in sync when the Stripe event destination is subscribed to those event types. For legal entities such as a German UG, Connect onboarding also requires real company formation, registry, representative/KYC, and payout bank details before `payouts_enabled=true` is expected.

Provider metering attribution is operator-controlled. Customer requests cannot pick their payout provider through headers or request JSON; until scheduler-integrated shares exist, configure `COMPUTEMESH_PROVIDER_SHARES` on the gateway host.

## Test Suite

- `services/gateway/tests/test_gateway_server.py` covers authentication, registered-key enforcement, OpenAI and Ollama model listings, OpenAI and Ollama non-streaming execution, SSE chunk streaming, balance checks, quota enforcement, Stripe Checkout wiring, signed webhook crediting, missing-signature rejection, provider registration/status/onboarding/refresh, admin provider listing, settlement listing, and admin provider settlement execution.
- `services/gateway/tests/test_inference_backend.py` covers fail-closed configuration, explicit synthetic opt-in, OpenAI-compatible runtime response parsing, usage propagation, invalid-response rejection, and URL validation.
