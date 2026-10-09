# Gateway Service

**Status:** implemented (Milestone M2 Foundation)

> **Current shared-serving note:** The compatibility backend documentation below is retained because those paths still exist. In addition, `services.gateway.live_server` now provides the integrated live shared-inference path: verified model catalog, authenticated provider control channel, persistent recovery state, private global placement through `ComputeMesh-ControlPlane`, Ed25519 verification of the returned execution plan, two-stage llama.cpp RPC execution, evidence/attestation and billing recovery. The public reference scheduler is research-only. Production scheduling remains gated on physical LAN/WAN measurements, and true upstream shared-runtime token streaming remains open.

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
- **Durable Agent Tasks:** Authenticated clients can create a model-bound agent session and queued first turn atomically through `POST /v1/agents/sessions`; session events and principal-bound approvals are exposed through bounded projections. A separately configured `MeshAgentWorker` claims queued/resumed turns through the policy-bound runtime, and `BackendModelCaller` adapts the existing inference backend for model execution.

The gateway's durable worker is an explicit deployment component. Set
`COMPUTEMESH_AGENTS_WORKER_ENABLED=1` to start it with the gateway; otherwise
the API continues to persist tasks without consuming the queue. The worker
uses the same `COMPUTEMESH_AGENTS_SESSION_DB` as the HTTP task endpoints, the
configured gateway inference backend and non-owner tool policy. Optional
`COMPUTEMESH_AGENTS_WORKER_COUNT`, `COMPUTEMESH_AGENTS_WORKER_MAX_TOKENS`,
`COMPUTEMESH_AGENTS_WORKER_BATCH` and
`COMPUTEMESH_AGENTS_WORKER_PERSISTENT_CONCURRENCY` tune bounded deployment
capacity. A worker failure is shut down before the HTTP server closes and does
not alter the legacy chat completion path.

## Endpoints

- `GET /healthz`: Service health check with non-sensitive Stripe readiness facts (`mode`, Checkout/session-store readiness, and webhook-secret presence); it never returns secret values.
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
- `POST /v1/agents/sessions`: Create an authenticated durable agent task with `agent_id`, `model` and `input`; optional bounded `priority` and `deadline_at` fields are persisted for worker scheduling.
- `POST /v1/agents/sessions/{session_id}/turns`: Queue authenticated follow-up
  input after the existing session is ready again, with the same optional
  scheduling fields.
- `GET /v1/agents/sessions`: List the caller's durable agent sessions.
- `GET /v1/agents/sessions/{session_id}/artifacts`: List immutable artifacts for
  one caller-owned session.
- `GET /v1/agents/artifacts/{ref_id}`: Download one artifact after its
  principal-bound reference is verified. The endpoint supports bounded HTTP
  byte ranges for resumable downloads and returns `206`/`Content-Range`.
- `GET /v1/agents/sessions/{session_id}/events`: Read a bounded reconnectable event cursor.
- `GET /v1/agents/approvals`: List the caller's pending or resolved agent approvals.
- `POST /v1/agents/approvals/{approval_id}`: Approve/reject one exact side-effect request and advance a waiting turn to explicit `resuming` state when applicable.
- `GET /v1/providers/status`: Provider-authenticated account and payable-balance status.
- `GET /v1/admin/providers`: Admin-only provider account and payable-balance listing.
- `GET /v1/admin/settlements`: Admin-only settlement record listing with optional `status` and `limit` query parameters.
- `POST /v1/admin/settlements/provider`: Admin-only provider settlement execution through Stripe Connect. Settlement records include the Stripe Transfer currency.

For an integrated control-plane deployment, inject an authenticated control
client into `build_gateway_agent_worker_runtime()` and set
`COMPUTEMESH_AGENTS_MESH_DISPATCH_ENABLED=1`. Queued sessions with
`environment_type=mesh` then use the verified NodeOS dispatcher, node routing,
leases and bounded retry policy from `AgentsPlatformRuntime`. Without both the
switch and the injected client, mesh turns fail closed; `none` and
`self_hosted` sessions continue through `BackendModelCaller`. Mesh turns do
not use gateway credit settlement yet because provider evidence and settlement
ownership for that route are still a separate release gate.

Mesh task creation may include a minimized `routing` object with required
capabilities, minimum free VRAM/context, throughput or latency requirements,
and allowed/excluded/preferred node IDs. The session store validates and
normalizes only those fields; the worker projects them into the authenticated
NodeOS route. Omitting `routing` preserves the existing model-only behavior.

Private deployments may additionally pass a `runtime_policy_resolver` to
`build_gateway_agent_worker_runtime()`. It receives the claimed session and
turn and may return only a minimized `RuntimePolicyEnvelope` (or its mapping),
which is validated and bound to the durable harness for that turn. This is the
injection point for private allow/deny, tool, side-effect, privacy and budget
policy; private scores, fraud, pricing, provider shares and credentials never
enter the public session or event contract. Omitting the resolver preserves the
existing deployment behavior.

The worker can also enforce immutable, versioned definitions from the
platform's `AgentDefinitionStore` with
`COMPUTEMESH_AGENTS_REQUIRE_DEFINITION=1`. A registered definition may bind an
allowed model set, a mesh node scope and a tool allowlist; those constraints
are applied at claim time without exposing the definition payload in the
session or event projection. The switch is off by default so existing
legacy-created tasks continue to use their established path.

The worker service uses persistent concurrency leases by default. Deployments
can tune the shared limits and fair queue with
`COMPUTEMESH_AGENTS_WORKER_GLOBAL_LIMIT`,
`COMPUTEMESH_AGENTS_WORKER_PRINCIPAL_LIMIT`,
`COMPUTEMESH_AGENTS_WORKER_SESSION_LIMIT`, optional
`COMPUTEMESH_AGENTS_WORKER_TENANT_LIMIT`,
`COMPUTEMESH_AGENTS_WORKER_FAIR_PRINCIPALS`,
`COMPUTEMESH_AGENTS_WORKER_AGING_SECONDS`,
`COMPUTEMESH_AGENTS_WORKER_MAX_CANDIDATES` and
`COMPUTEMESH_AGENTS_WORKER_CONCURRENCY_LEASE_SECONDS`. With persistent
concurrency enabled, the SQLite-backed admission gate applies these limits
across worker processes instead of giving each process an independent quota.

The canonical `services.gateway.live_server` bootstrap supplies this client
automatically after the integrated TLS control plane is started. When the
worker switch is enabled there, the worker is started only after the live
gateway backend and confidential gateway gates have succeeded, and it is
closed before the control plane during shutdown. The compatibility
`services.gateway.server` entry point intentionally remains client-free and
therefore keeps mesh dispatch fail-closed.

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

The compatibility backend remains useful for local/demo operation. The integrated shared path is now `python -m services.gateway.live_server`; it dispatches reserved planner-selected multi-node execution through the live orchestrator rather than using this compatibility bridge.

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

Provider metering attribution is operator-controlled. Customer requests cannot pick their payout provider through headers or request JSON; live shared execution derives attribution from verified executed placement/evidence. Compatibility operation may still use `COMPUTEMESH_PROVIDER_SHARES`.

## Test Suite

- `services/gateway/tests/test_gateway_server.py` covers authentication, registered-key enforcement, OpenAI and Ollama model listings, OpenAI and Ollama non-streaming execution, SSE chunk streaming, balance checks, quota enforcement, Stripe Checkout wiring, signed webhook crediting, missing-signature rejection, provider registration/status/onboarding/refresh, admin provider listing, settlement listing, and admin provider settlement execution.
- `services/gateway/tests/test_inference_backend.py` covers fail-closed configuration, explicit synthetic opt-in, OpenAI-compatible runtime response parsing, usage propagation, invalid-response rejection, and URL validation.
- Live shared bootstrap/runtime tests cover private placement wiring, recovery and fail-closed execution invariants; physical cross-machine validation remains a real-hardware gate rather than a mock substitute.
