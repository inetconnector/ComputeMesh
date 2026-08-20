# Model Registry Service

**Status:** planned component

## Purpose

Canonical metadata for models, immutable versions, artifacts, and legal/runtime compatibility.

## Responsibilities

- model/version records
- manifest validation
- artifact digests
- shard manifests
- signatures
- runtime compatibility
- partition constraints
- license metadata

## Non-goals

- serving arbitrary user binaries
- changing immutable model versions in place

## Canonical interfaces

- scheduler
- node artifact preparation
- artifact storage

## M1 scope

- one model manifest
- one partition/shard representation
- digest verification path

## Required tests / evidence

- canonicalization
- digest mismatch
- signature failure
- unsupported runtime
- immutable version

## Security and reliability rules

- Treat external inputs as untrusted.
- Use bounded messages/resources.
- Preserve idempotency for state changes.
- Emit structured errors and metrics without raw prompt/output content.
- Do not widen the V1 arbitrary-code boundary without an accepted ADR.

## Implementation status

No production implementation exists yet. Update this file when the component acquires real entry points, configuration, dependencies, and run/test commands.
