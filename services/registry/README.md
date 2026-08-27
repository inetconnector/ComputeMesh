# Model Registry Service

**Status:** standalone production registry service planned; public artifact/model-contract foundations and live catalog handling implemented.

## Purpose

Canonical metadata for models, immutable versions, artifacts, and legal/runtime compatibility.

## Current implemented foundations

ComputeMesh already has public building blocks that belong to this domain:

- model/artifact JSON schemas and content-digest contracts;
- bounded GGUF metadata inspection and single-GGUF manifest generation in `tools/benchmark/gguf_manifest.py`;
- model size/SHA-256/runtime binding used by M1 experiment bundles and shared-runtime proof tooling;
- verified live model-catalog loading used by the live gateway;
- artifact/runtime identity checks in the current research/live execution path.

These foundations are **not** yet a complete durable multi-user production registry service with artifact distribution, lifecycle APIs and HA storage.

## Responsibilities of the future standalone service

- model/version records
- manifest validation
- artifact digests
- shard manifests
- signatures
- runtime compatibility
- partition constraints
- license metadata
- artifact availability/preparation state

## Non-goals

- serving arbitrary user binaries
- changing immutable model versions in place
- weakening content-addressed artifact identity

## Canonical interfaces

- private production placement/control plane
- public gateway/model catalog
- provider artifact preparation
- artifact storage/cache

## Current readiness gap

The current schema/tooling is sufficient for bounded M1 single-GGUF identity and live catalog use. A production registry still needs durable service APIs, signed artifact lifecycle/distribution, complete multi-shard identity/order semantics, authorization and production storage/HA decisions.

## Required tests / evidence

- canonicalization
- digest mismatch
- signature failure
- unsupported runtime
- immutable version
- shard membership/order when multi-shard support is introduced
- authorization and replay/idempotency for future stateful APIs

## Security and reliability rules

- Treat external metadata and artifacts as untrusted.
- Bound file/message sizes and parsing work.
- Verify immutable digests before use.
- Preserve idempotency for state changes.
- Emit structured errors/metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

See `docs/CURRENT_STATUS.md` for current system status and `tools/benchmark/README.md` for current model-manifest tooling.
