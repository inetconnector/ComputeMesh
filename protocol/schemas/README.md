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

Initial message payloads:

- `reserve_capacity_payload.schema.json`
- `commit_reservation_payload.schema.json`
- `cancel_job_payload.schema.json`

These payload contracts intentionally cover only `ReserveCapacity`, `CommitReservation`, and `CancelJob`, because those operations are already specified in `PROTOCOL.md`. Other protocol operations receive their own contracts only when implemented.

## Rules

- schemas use JSON Schema Draft 2020-12;
- protocol and schema versions are explicit;
- monetary quantities are integers, never floating-point currency values;
- mutable distributed resources carry a monotonic `revision` where applicable;
- content-addressed artifacts use `sha256:<hex>` in the initial draft;
- unknown fields are rejected by security-sensitive base/state/message contracts unless explicitly designed otherwise;
- adding a field that changes security, billing, privacy, or compatibility semantics requires the matching documentation/ADR update;
- these schemas may change before protocol v1 freeze.

The benchmark harness produces node-profile/benchmark-result documents compatible with these contracts. The protocol package validates the common control envelope and the initial message-specific payloads. The orchestrator handlers then bind validated requests to durable state effects.

Authentication, authorization, capability negotiation, and the remaining message families are still separate future responsibilities.
