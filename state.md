# ComputeMesh State

**Last updated:** 2026-08-21  
**Phase:** M0 — contracts, durable orchestration, protocol/session foundations, and measurable lab/runtime benchmarking  
**Production services/runtime:** none  
**Executable engineering tooling:** inventory + TCP network + llama-bench adapters, durable orchestrator reference, initial control handlers, authentication-gated node-session semantics  
**Public release:** none

## Repository

- repository: `inetconnector/ComputeMesh`
- default branch: `main`
- documentation v0.2: `cf85a47`
- contracts/benchmark bootstrap: `7df5b4e`
- transactional persistence/schema admission: `bfea175`
- control envelope/structured errors: `9ed33be`
- TCP network microbenchmark: `197a1ad`
- llama-bench prefill/decode adapter: `6b0356a`
- initial durable control handlers: `9bb4a72` + restriction `b23bf60`
- authentication-gated node-session semantics: `d7a110e`

## What exists

- synchronized English/German root READMEs;
- M0 architecture/protocol/security/benchmark/failure/privacy/data-model documentation;
- Draft-2020-12 machine-readable contracts;
- node inventory, TCP network, and llama-bench measurement tooling;
- deterministic Job/Reservation state semantics;
- transactional SQLite reference persistence with durable idempotency, revisions, restart recovery, leases, request fingerprints, and schema migration;
- atomic reservation → job + stage binding;
- transport-neutral control-envelope parser and structured errors;
- message-specific payload contracts/handlers for `ReserveCapacity`, `CommitReservation`, and `CancelJob`;
- transport-neutral node-session state machine matching the documented Hello/Auth/Capability/Profile/Benchmark/Ready lifecycle;
- mandatory injected `AuthenticationVerifier` interface with no permissive default;
- challenge-bound verification inputs, credential-expiry checks, hello/authenticated-node identity matching, capability negotiation, profile/benchmark revision gating, drain, close, and external termination semantics.

## Verified M0 implementation evidence

Previously verified and unchanged:

- inventory collector tests: 3/3 passing;
- TCP network benchmark tests: 4/4 passing;
- llama-bench adapter tests: 6/6 passing;
- loopback network output and converted llama-bench fixture outputs validate against benchmark-result schema.

Current control/session verification:

- control/orchestrator handler and persistence regression workspace: 37/37 passing;
- protocol envelope + message payload + schema + node-session suite: 29/29 passing;
- node-session-specific tests: 14/14 passing;
- relevant Python modules pass `py_compile`.

Session tests cover:

- normal `Hello -> Authenticate -> CapabilityNegotiation -> ProfileSync -> BenchmarkStatus -> READY` path;
- verifier receives session ID and challenge;
- failed/expired credentials do not advance state;
- authenticated node ID must match advertised stable node ID when one is present;
- unadvertised auth methods are rejected before verifier invocation;
- required capability mismatch prevents readiness;
- authentication cannot be skipped;
- credential expiry blocks later session progress;
- benchmark status must match synced profile revision;
- drain is allowed only from `READY`;
- external revocation signal can terminate a session.

Important evidence boundary:

- `AuthenticationVerifier` is an interface, not a production verifier;
- no key algorithm, credential format, issuer, OS key store, enrollment protocol, rotation service, or revocation backend has been selected;
- ADR 0005 remains Proposed;
- TCP benchmark remains loopback-only evidence;
- llama-bench adapter still lacks real target-model/GPU evidence;
- no distributed inference result exists yet.

## What does not exist

- real two-node hardware/network evidence;
- real target-lab llama.cpp prefill/decode evidence;
- production provider node agent;
- distributed runtime/shared inference;
- gateway/API/scheduler;
- production orchestrator service/database;
- production node credential verifier/enrollment/key lifecycle;
- wire binding for NodeHello/NodeAuthenticate/ProfileSync and remaining node/runtime/artifact messages;
- registry/verification/billing/telemetry/SDK/UI;
- production release/update system.

## Session lifecycle now represented

```text
CONNECTED
 -> HELLO_RECEIVED
 -> AUTHENTICATED
 -> CAPABILITIES_NEGOTIATED
 -> PROFILE_SYNCED
 -> READY
 -> DRAINING
 -> CLOSED
```

Authentication is gated by an injected verifier. A successful decision must include stable node identity, provider principal, and a timezone-aware future credential expiry. The verifier is expected to bind proof to both session ID and per-session challenge. No default verifier exists.

## ADR status

Accepted only:

- ADR 0001 — repository bootstrap.

Still proposed:

- ADR 0002 — M1 runtime baseline;
- ADR 0003 — control/data transport;
- ADR 0004 — model/artifact identity;
- ADR 0005 — node identity/key lifecycle;
- ADR 0006 — telemetry envelope;
- ADR 0007 — ledger units.

The session skeleton does **not** constitute acceptance of ADR 0005.

## Primary blockers

1. No real two-node profiles/cross-node network results exist yet.
2. No real local llama.cpp prefill/decode baseline exists yet.
3. M1 runtime baseline remains unaccepted until the required real two-node spike.
4. ADR 0005 still needs a concrete credential/key/enrollment/rotation/revocation design and production verifier.
5. NodeHello/Auth/Profile wire contracts and remaining node/runtime/artifact handlers are not bound yet.
6. No activation-payload transport benchmark exists yet.
7. WAN viability and verification economics remain unmeasured.
8. No release/update security implementation exists.

## Next actions in order

1. Run `benchmark.py` on two real lab machines and retain both profiles.
2. Run `network_benchmark.py` between those machines in both directions on a trusted LAN.
3. Run `llama_bench_adapter.py` with the selected local GGUF/model and current `llama-bench` on each relevant machine.
4. Compare prefill/decode results and choose the exact two-node M1 spike configuration.
5. Specify/implement the concrete ADR-0005 credential verification path without weakening the no-default verifier boundary.
6. Define and bind NodeHello/NodeAuthenticate/Capability/Profile/Benchmark wire payloads to the session skeleton.
7. Execute the llama.cpp-oriented ADR 0002 runtime spike behind the ComputeMesh boundary.
8. Add activation-payload-size modes and controlled latency/jitter/loss experiments.
9. Produce first correct two-node shared inference and begin scheduler calibration.

## Bilingual README rule

`README.md` and `README.de.md` are synchronized project entry points and must be updated together for every public-facing change.
