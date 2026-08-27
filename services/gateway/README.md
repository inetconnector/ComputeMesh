# Gateway Service

**Status:** implemented (M2 experimental shared-serving foundation)

## Purpose

Public OpenAI-compatible and Ollama-compatible API entry point, streaming facade, credential authentication layer, billing integration, and live shared-inference entry point.

## Current architecture

The gateway now has two distinct runtime roles:

1. compatibility/demo backends (`openai_compatible`, `ollama`, explicit synthetic test mode), and
2. the live shared-inference server in `services.gateway.live_server`.

The live server is integrated with the orchestrator, authenticated provider control channel, verified live model catalog, persistent recovery state and the public/private placement boundary. In production placement mode it sends the complete bounded live candidate/network snapshot to the private `ComputeMesh-ControlPlane`, verifies the returned Ed25519-signed execution plan, reserves/dispatches the selected two-node llama.cpp RPC execution, collects execution evidence/attestations and reconciles billing state.

The disclosed public reference scheduler remains research-only and requires explicit experimental opt-in.

## Important product boundary

The current live executor still supports exactly two execution stages and llama.cpp RPC remains a trusted-lab/private-network runtime. Production scheduling must remain gated until physical heterogeneous-node, controlled LAN and real WAN measurements establish safe operating envelopes. Current streaming is a gateway facade; true upstream shared-runtime token/chunk streaming with cancellation/backpressure remains a product-readiness task.

## Main endpoints

- `GET /healthz`: service health check.
- `GET /v1/models`: OpenAI-compatible model list.
- `POST /v1/chat/completions`: OpenAI-compatible inference.
- `GET /api/tags`: Ollama-compatible model list.
- `POST /api/chat`: Ollama-compatible chat inference.
- `POST /api/generate`: Ollama-compatible prompt inference.
- billing/provider/admin endpoints remain implemented by the gateway billing routes.

## Live shared-inference startup

Use:

```text
python -m services.gateway.live_server
```

Required live inputs include a verified model catalog/root, persistent identity/orchestrator state, a real `llama-server`, a shared work root, provider-control TLS material and placement configuration. Production placement defaults to the private control plane and fails closed when its URL/token/signing public key/key id are absent or invalid.

The private umbrella repository `ComputeMesh-ControlPlane` supplies a Windows development bootstrap and `START-ALL.bat` that wires matching local development credentials while preserving the real runtime/model/provider prerequisites.

## Compatibility runtime configuration

The non-live compatibility gateway continues to support an OpenAI-compatible runtime or Ollama daemon. Synthetic completion is retained only as an explicit test/development fixture and requires both `COMPUTEMESH_INFERENCE_BACKEND=synthetic` and `COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE=1`.

## Billing and integrity

Successful inference is metered through the double-entry ledger. Customer input cannot select payout providers. Live shared execution derives provider attribution from verified executed placement/evidence. Failed, cancelled or unverified shared jobs are not settled; startup and billing-outbox recovery close known crash windows.

Stripe Checkout/Connect support remains fail-closed when required Stripe credentials/state are unavailable.

## Tests

Gateway tests cover authentication, OpenAI/Ollama compatibility, quota/billing/Stripe behavior, fail-closed runtime configuration and live shared bootstrap behavior. Cross-machine physical execution and network viability are intentionally tracked as hardware product-readiness validation rather than mocked unit success.
