# ComputeMesh machine-readable schemas

**Status:** M0/M1 draft contracts; not wire-stable.

This directory is the machine-readable implementation of concepts defined in `PROTOCOL.md`, `docs/DATA_MODEL.md`, `docs/BENCHMARK_SPEC.md`, and the ADR backlog.

## Current schemas

Core/control:

- `control_envelope.schema.json`
- `error.schema.json`
- `node_profile.schema.json`
- `benchmark_result.schema.json`
- `model_manifest.schema.json`
- `shard_manifest.schema.json`
- `reservation.schema.json`
- `job.schema.json`

Initial durable orchestration message payloads:

- `reserve_capacity_payload.schema.json`
- `commit_reservation_payload.schema.json`
- `cancel_job_payload.schema.json`

Initial node-session payloads:

- `node_hello_payload.schema.json`
- `node_authenticate_payload.schema.json`
- `capability_negotiation_payload.schema.json`
- `drain_request_payload.schema.json`

`NodeProfileUpdate` intentionally reuses the complete `node_profile.schema.json` document rather than defining a second profile shape. `BenchmarkReport` likewise reuses `benchmark_result.schema.json`. `protocol/session_contracts.py` maps those six documented session message types to their contracts.

The durable orchestration contracts remain separate from the node-session contracts so extending readiness/session semantics cannot silently enlarge the set of operations handled by `services/orchestrator/handlers.py`.

## M1 evidence-binding extensions

The v1 documents remain backward compatible while carrying stronger experiment traceability when available:

- `model_manifest.schema.json` accepts optional `layer_count` for runtimes/planners that need a structural layer count. Legacy manifests may omit it.
- `benchmark_result.schema.json` conditions may include `local_node_id`, `peer_node_id`, and `peer_identity_binding`.
- `peer_node_id` and `peer_identity_binding` are paired: neither may appear without the other.
- current TCP benchmark peer self-report uses `peer_identity_binding = unauthenticated_server_report_v1`.
- legacy/imported evidence may be explicitly labelled `caller_asserted_v1` where the caller supplies the association.

These fields improve evidence bookkeeping but do not strengthen the benchmark transport. In particular, `unauthenticated_server_report_v1` is **not** an authenticated node identity assertion: the TCP benchmark remains an unauthenticated, unencrypted trusted-private-LAN tool. The separate ADR-0005 Ed25519/session path is the narrow M1 reference authentication mechanism.

## Rules

- schemas use JSON Schema Draft 2020-12;
- protocol and schema versions are explicit;
- monetary quantities are integers, never floating-point currency values;
- mutable distributed resources carry a monotonic `revision` where applicable;
- content-addressed artifacts use `sha256:<hex>` in the initial draft;
- unknown fields are rejected by security-sensitive base/state/message contracts unless explicitly designed otherwise;
- adding a field that changes security, billing, privacy, or compatibility semantics requires the matching documentation/ADR update;
- these schemas may change before protocol v1 freeze.

The benchmark harness produces node-profile/benchmark-result documents compatible with these contracts. The protocol package validates the common control envelope, the initial durable-message payloads, and the initial node-session payload family. The orchestrator handlers bind only their documented durable requests to SQLite effects; `NodeSessionWireHandler` separately binds the readiness/session family to the in-memory semantic session.

ADR 0005 is accepted only for the narrow M1 reference node-identity implementation. Production provider/user authentication around identity APIs, authorization, transport security, protected private-key storage, active-session revocation fan-out, and the remaining runtime/artifact/heartbeat message families still require additional design and implementation.
