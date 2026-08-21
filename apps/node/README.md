# ComputeMesh Provider Node

**Status:** production provider application remains planned. Shared M0 session semantics and a Windows **Lab Setup** now exist.

## For users today

The current runnable Windows path is **not** a provider-node installer. For M0 lab measurements, use the repository-root `SETUP.cmd` or the direct launchers under `setup/`.

That setup can:

- capture a local CPU/RAM/GPU profile;
- run the trusted-LAN benchmark server/client workflow;
- run/select llama.cpp `llama-bench` and a local GGUF model;
- run the current test suites.

It does not enroll the computer into a public ComputeMesh network, expose it as paid capacity, or install a background provider service.

## Planned provider-node purpose

The eventual Windows-first provider agent is responsible for:

- enrollment and local identity integration;
- hardware/runtime discovery and benchmark publication;
- availability, power, thermal, and sharing policy;
- capacity reservation handling;
- artifact cache orchestration;
- constrained runtime-worker supervision;
- telemetry;
- safe drain, update, rollback, diagnostics, and uninstall.

## Current shared session foundation

`protocol/node_session.py` models:

```text
CONNECTED -> HELLO_RECEIVED -> AUTHENTICATED
-> CAPABILITIES_NEGOTIATED -> PROFILE_SYNCED -> READY
-> DRAINING -> CLOSED
```

It requires an injected `AuthenticationVerifier` with no permissive default and checks credential expiry, node-ID consistency, capabilities, profile/benchmark revision, drain ordering, and external termination.

This is **not production authentication**. Credential format, key algorithm, enrollment/issuer, OS-protected key storage, rotation, revocation backend, and network binding remain open under ADR 0005.

## M1 target

- enroll two nodes with the eventually selected credential mechanism;
- publish versioned profiles and benchmark evidence;
- accept a short reservation lease;
- prepare a verified artifact;
- start one constrained runtime stage;
- drain safely.

The new Lab Setup is intended to make the hardware/network/runtime evidence for that work easy to collect; it does not replace the future provider application.
