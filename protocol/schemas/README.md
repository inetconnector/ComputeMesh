# ComputeMesh machine-readable schemas

**Status:** M0 draft contracts; not wire-stable.

This directory is the first machine-readable implementation of concepts defined in `PROTOCOL.md`, `docs/DATA_MODEL.md`, `docs/BENCHMARK_SPEC.md`, and the ADR backlog.

Current schemas:

- `node_profile.schema.json`
- `benchmark_result.schema.json`
- `model_manifest.schema.json`
- `shard_manifest.schema.json`
- `reservation.schema.json`
- `job.schema.json`

Rules:

- schemas use JSON Schema Draft 2020-12;
- `schema_version` is explicit;
- monetary quantities are integers, never floating-point currency values;
- mutable distributed resources carry a monotonic `revision` where applicable;
- content-addressed artifacts use `sha256:<hex>` in the initial draft;
- adding a field that changes security, billing, privacy, or compatibility semantics requires the matching documentation/ADR update;
- these schemas are M0 contracts and may change before protocol v1 freeze.

The benchmark harness in `tools/benchmark/` produces a node profile and benchmark result compatible with the semantic requirements represented here. Full JSON-Schema validation is intentionally kept separate from collection so the initial collector has no third-party runtime dependency.
