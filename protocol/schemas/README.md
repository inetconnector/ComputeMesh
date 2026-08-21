# ComputeMesh machine-readable schemas

**Status:** M0 draft contracts; not wire-stable.

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

Authentication **mechanism**, enrollment, authorization beyond authenticated actor binding, transport security, and the remaining runtime/artifact/heartbeat message families are still future responsibilities. ADR 0005 remains Proposed.
