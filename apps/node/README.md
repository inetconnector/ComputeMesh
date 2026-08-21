# ComputeMesh Provider Node

**Status:** production provider application remains planned. Shared M0 session semantics and a cross-platform Windows/Linux **Lab Setup** now exist.

## For users today

The current runnable path is **not** a provider-node installer.

- Windows: run repository-root `SETUP.cmd`.
- Linux: run repository-root `./setup.sh` (or `bash setup.sh` if executable permissions were lost).

The setup can capture CPU/RAM/GPU profiles, run the trusted-LAN benchmark server/client workflow, run/select llama.cpp `llama-bench` with a local GGUF, and execute current test suites.

It does not enroll the computer into a public ComputeMesh network, expose it as paid capacity, or install a background provider service.

## Planned provider-node purpose

The eventual provider agent is responsible for enrollment/identity integration, hardware/runtime discovery, benchmark publication, availability/power/thermal/sharing policy, reservations, artifact cache, constrained runtime-worker supervision, telemetry, and safe drain/update/rollback/diagnostics/uninstall.

Windows remains the first provider-product UX target, but the M0 measurement layer is intentionally cross-platform because real compute capacity may run Linux.

## Current shared session foundation

`protocol/node_session.py` models:

```text
CONNECTED -> HELLO_RECEIVED -> AUTHENTICATED
-> CAPABILITIES_NEGOTIATED -> PROFILE_SYNCED -> READY
-> DRAINING -> CLOSED
```

It requires an injected `AuthenticationVerifier` with no permissive default and checks credential expiry, node-ID consistency, capabilities, profile/benchmark revision, drain ordering, and external termination.

This is **not production authentication**. Credential format, key algorithm, enrollment/issuer, protected key storage, rotation, revocation backend, and network binding remain open under ADR 0005.

## M1 target

- collect reproducible evidence from two nodes, including mixed Windows/Linux if useful;
- enroll two nodes with the eventually selected credential mechanism;
- publish versioned profiles and benchmark evidence;
- accept a short reservation lease;
- prepare a verified artifact;
- start one constrained runtime stage;
- drain safely.

The Lab Setup makes the hardware/network/runtime evidence easier to collect; it does not replace the future provider application.
