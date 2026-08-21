# ComputeMesh machine-readable schemas

**Status:** M0 draft contracts; not wire-stable.

This directory is the machine-readable implementation of concepts defined in `PROTOCOL.md`, `docs/DATA_MODEL.md`, `docs/BENCHMARK_SPEC.md`, and the ADR backlog.

Current schemas:

- `control_envelope.schema.json`
- `error.schema.json`
- `node_profile.schema.json`
- `benchmark_result.schema.json`
- `model_manifest.schema.json`
- `shard_manifest.schema.json`
- `reservation.schema.json`
- `job.schema.json`

Rules:

- schemas use JSON Schema Draft 2020-12;
- protocol and schema versions are explicit;
- monetary quantities are integers, never floating-point currency values;
- mutable distributed resources carry a monotonic `revision` where applicable;
- content-addressed artifacts use `sha256:<hex>` in the initial draft;
- unknown fields are rejected by security-sensitive base-envelope/state contracts unless explicitly designed otherwise;
- adding a field that changes security, billing, privacy, or compatibility semantics requires the matching documentation/ADR update;
- these schemas are M0 contracts and may change before protocol v1 freeze.

The benchmark harness produces node-profile/benchmark-result documents compatible with the semantic requirements represented here. The protocol package now also has a transport-neutral parser for the common control envelope. Authentication, authorization, capability negotiation, and message-specific payload validation remain separate responsibilities.
