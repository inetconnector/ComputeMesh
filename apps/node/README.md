# ComputeMesh Provider Node

**Status:** a runnable **live development provider agent** now exists for the authenticated two-node/product-readiness path. A hardened production installer is still planned; a restartable, least-privilege Linux systemd service template is available under `deploy/systemd/`. The cross-platform Windows/Linux **Lab Setup** remains available and is not replaced.

## Lab setup

The existing lab path remains unchanged:

- Windows: run repository-root `SETUP.cmd`.
- Linux: run repository-root `./setup.sh` (or `bash setup.sh` if executable permissions were lost).

The setup can capture CPU/RAM/GPU profiles, run the trusted-LAN benchmark server/client workflow, run/select llama.cpp `llama-bench` with a local GGUF, execute the shared-runtime proof tooling, and run current test suites.

The Lab Setup by itself does not enroll a computer into a public paid network or install a background provider service.

### Linux service template

For an operator-managed Linux node, copy
`deploy/systemd/provider.env.example` to `/etc/computemesh/provider.env`, fill
only the node paths/identifiers, install
`deploy/systemd/computemesh-node.service` as a systemd unit, and enable it after
the evidence files and protected key have been provisioned. The unit uses the
existing provider CLI, restarts after transient failure, and applies filesystem,
identity and address-family hardening. It does not create enrollment material,
copy credentials or claim that a node is production-ready by itself. Optional
Inference, model-preparation and typed-environment settings in the env file are
forwarded to the same provider CLI; leaving them empty keeps those capabilities
disabled.

## Live development provider agent

`apps/node/provider_agent.py` is the executable provider-side counterpart to the existing persistent live control-plane listener. It is intended for real development/product-readiness tests with already enrolled nodes and measured evidence.

It performs:

- TLS server verification using an explicitly supplied CA file;
- Ed25519 challenge authentication using the enrolled node private key;
- capability negotiation (`execution_attestation_v1`, `live_runtime_registration_v1`,
  `capacity_reservation_v1` and optional `inference_v1`);
- `NodeProfileUpdate` publication;
- llama.cpp `RuntimeAdvertisement` publication with a concrete build number/commit and RPC endpoint;
- publication of measured prefill/decode benchmark documents and optional measured network reports;
- publication of a bounded model inventory from the local NodeOS catalogue;
- reconnect/backoff through the existing persistent provider channel;
- authenticated `ExecutionAttestationRequest` handling through `NodeAttestationService`;
- optional authenticated `InferenceRequest` handling through a strictly bounded
  loopback OpenAI-compatible NodeOS endpoint. The capability is advertised only
  when `--inference-endpoint` (or `COMPUTEMESH_NODEOS_INFERENCE_ENDPOINT`) is
  explicitly configured; the same endpoint can provide bounded SSE chunks via
  the negotiated `inference_stream_v1` capability. The adapter closes an
  in-flight response on cancellation; a deployment that owns the model process
  may inject an explicit `on_cancel` callback to stop that process as well.
  No shared model server is terminated by default.
- optional authenticated model preparation through
  `--model-preparation-manifest` (or
  `COMPUTEMESH_MODEL_PREPARATION_MANIFEST`). The manifest is a local operator
  allowlist with pinned Hugging Face repository, 40-character revision,
  filename, size and SHA-256; requests that differ from it are rejected.
- optional typed Mesh-environment handling through an injected
  `environment_executor`; this advertises `mesh_environment_v1` and accepts
  only validated `prepare`, `heartbeat`, `execute` and `shutdown` requests
  bound to the authenticated session. It exposes no shell or command fallback.
  The executable agent enables the concrete bounded NodeOS adapter with
  `--environment-root` (or `COMPUTEMESH_NODEOS_ENVIRONMENT_ROOT`); the adapter
  provides lease-bound health, inference and symlink-safe workspace operations.

It deliberately does **not** contain the private production scheduler, pricing, reputation, fraud, marketplace or settlement implementation.

### Required inputs

The provider must already have:

- a node ID enrolled in the control-plane identity store;
- the matching Ed25519 private key in a protected local file;
- a real measured node profile JSON;
- real measured `llama_cpp_prefill` and `llama_cpp_decode` benchmark JSON;
- a reachable llama.cpp RPC worker endpoint;
- the exact llama.cpp build number and commit advertised by that worker;
- the CA certificate used to verify the provider-control TLS listener.

Example:

```bash
python -m apps.node.provider_agent \
  --control-host 10.0.0.10 \
  --control-port 7443 \
  --ca-file /etc/computemesh/control-ca.pem \
  --server-hostname computemesh-control \
  --node-id node_xxx \
  --private-key /var/lib/computemesh/node-ed25519.pem \
  --profile /var/lib/computemesh/evidence/node_profile.json \
  --prefill /var/lib/computemesh/evidence/prefill.json \
  --decode /var/lib/computemesh/evidence/decode.json \
  --rpc-host 10.0.0.22 \
  --rpc-port 50052 \
  --llama-build-number 12345 \
  --llama-build-commit abcdef123456 \
  --inference-endpoint http://127.0.0.1:8080/v1/chat/completions \
  --model-preparation-manifest /var/lib/computemesh/evidence/model-preparation.json \
  --environment-root /var/lib/computemesh/agent-environments
```

The manifest uses `schema_version: 1` and a `models` object. Each entry must
contain `repo_id`, `filename`, `revision`, `sha256`, `size_bytes`,
`layer_count`, `quantization` and `license_id`. The provider advertises
`model_preparation_v1` only when this allowlist is configured. Installation
still occurs only after the control plane has authorized the preparation
request; the existing NodeOS model manager performs the download, resume,
digest, GGUF and storage checks.

The environment capability is intentionally callback-based in this public
provider agent. A deployment must supply the bounded NodeOS implementation and
enforce its resource, path and network policy; the wire adapter is not an OS
process sandbox by itself.

For a dedicated NodeOS process that owns the managed model engine, set
`COMPUTEMESH_NODEOS_STOP_MANAGED_MODEL_ON_CANCEL=1`. The provider then connects
cancellation to the verified local `ModelEngineService` only when the inference
endpoint matches that engine's loopback origin. This stops the whole managed
`llama-server`, so it must remain disabled for shared or externally supervised
model runtimes.

Use `--network-report <path>` repeatedly to publish existing measured `tcp_network_path` reports. The agent never fabricates missing benchmark/network evidence.

The provider handles `SIGTERM` and `SIGINT` through the persistent client stop
path. The active control socket is unblocked, in-flight request cancellation is
propagated, and the service can exit for a supervisor restart without leaving
the reconnect loop stuck in a blocking read.

### Security boundary

The current agent is appropriate for the controlled development/live-validation path, not yet a public-internet production daemon. In particular:

- the node private key must never be committed or copied into the public repository;
- upstream llama.cpp RPC must remain on a trusted private network/VPN/tunnel and must not be exposed as an unauthenticated public Internet service;
- production protected-key storage, install/service management, update/rollback, stronger network isolation and complete revocation fan-out remain product-hardening work.

## Shared session foundation

`protocol/node_session.py` models:

```text
CONNECTED -> HELLO_RECEIVED -> AUTHENTICATED
-> CAPABILITIES_NEGOTIATED -> PROFILE_SYNCED -> READY
-> DRAINING -> CLOSED
```

The wire path requires an injected `AuthenticationVerifier` with no permissive default and checks credential expiry, node-ID consistency, capabilities, profile/benchmark revision, drain ordering, and external termination. The live provider agent now exercises those semantics over the persistent TLS channel rather than bypassing them.

## Remaining provider-product work

The production provider product still needs:

- protected OS-backed node-key storage and polished enrollment UX;
- deployment-specific GPU/device isolation and physical process/resource
  enforcement beyond the provider admission lease;
- constrained runtime-worker lifecycle supervision;
- artifact cache/preparation lifecycle;
- availability/power/thermal/sharing policy;
- production service/installer packages;
- safe drain/update/rollback/diagnostics/uninstall;
- production network/data-plane hardening.

The Lab Setup, live development agent and future production installer are distinct layers. Existing lab/evidence workflows remain required for reproducible physical validation.
