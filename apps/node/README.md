# ComputeMesh Provider Node

**Status:** a runnable **live development provider agent** now exists for the authenticated two-node/product-readiness path. A hardened production provider installer/background service is still planned. The cross-platform Windows/Linux **Lab Setup** remains available and is not replaced.

## Lab setup

The existing lab path remains unchanged:

- Windows: run repository-root `SETUP.cmd`.
- Linux: run repository-root `./setup.sh` (or `bash setup.sh` if executable permissions were lost).

The setup can capture CPU/RAM/GPU profiles, run the trusted-LAN benchmark server/client workflow, run/select llama.cpp `llama-bench` with a local GGUF, execute the shared-runtime proof tooling, and run current test suites.

The Lab Setup by itself does not enroll a computer into a public paid network or install a background provider service.

## Live development provider agent

`apps/node/provider_agent.py` is the executable provider-side counterpart to the existing persistent live control-plane listener. It is intended for real development/product-readiness tests with already enrolled nodes and measured evidence.

It performs:

- TLS server verification using an explicitly supplied CA file;
- Ed25519 challenge authentication using the enrolled node private key;
- capability negotiation (`execution_attestation_v1`, `live_runtime_registration_v1`);
- `NodeProfileUpdate` publication;
- llama.cpp `RuntimeAdvertisement` publication with a concrete build number/commit and RPC endpoint;
- publication of measured prefill/decode benchmark documents and optional measured network reports;
- reconnect/backoff through the existing persistent provider channel;
- authenticated `ExecutionAttestationRequest` handling through `NodeAttestationService`.

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
  --llama-build-commit abcdef123456
```

Use `--network-report <path>` repeatedly to publish existing measured `tcp_network_path` reports. The agent never fabricates missing benchmark/network evidence.

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
- provider-enforced capacity leases/resource limits;
- constrained runtime-worker lifecycle supervision;
- artifact cache/preparation lifecycle;
- availability/power/thermal/sharing policy;
- production service/installer packages;
- safe drain/update/rollback/diagnostics/uninstall;
- production network/data-plane hardening.

The Lab Setup, live development agent and future production installer are distinct layers. Existing lab/evidence workflows remain required for reproducible physical validation.
