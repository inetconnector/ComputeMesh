# ComputeMesh Protocol Outline

This document captures the initial protocol direction. It is not yet a stable specification.

## Design Goals

- model-aware scheduling
- low-overhead inference data path
- signed and reproducible shard execution
- explicit privacy and trust constraints
- idempotent state transitions
- auditable job, verification, and billing records
- compatibility with common OpenAI-style API clients

## Public API

The gateway should expose OpenAI-compatible endpoints first:

```text
POST /v1/chat/completions
POST /v1/responses
POST /v1/embeddings
GET  /v1/models
```

ComputeMesh-specific extensions may include:

- `privacy_tier`
- `deadline_ms`
- `max_budget`
- `quality_target`
- `preferred_regions`
- `verification_level`
- `allow_consumer_nodes`
- `allow_datacenter_nodes`

## Node Control Protocol

Initial node messages:

- `NodeHello`
- `NodeAuthenticate`
- `NodeProfileUpdate`
- `BenchmarkReport`
- `AvailabilityUpdate`
- `JobAssignment`
- `ShardPrepare`
- `ShardReady`
- `ExecuteSegment`
- `SegmentResult`
- `VerificationTrace`
- `DrainRequest`
- `FailureReport`

All commands from the control plane must be authenticated, authorized, and replay-safe.

## Data Plane Candidates

M0 and M3 must compare:

- gRPC streaming
- QUIC streams
- transport-specific backpressure
- latency under jitter
- throughput under packet loss
- connection recovery behavior

The data plane should carry only the minimal execution data required for approved inference workloads.

## Manifests

Model manifest fields:

- model id
- version
- architecture
- layer count
- expert count
- quantization
- memory requirement
- KV-cache requirement
- backend compatibility
- supported partitioning modes
- license metadata
- safety or privacy constraints

Shard manifest fields:

- shard id
- model id and version
- content hash
- signature
- byte size
- tensor/layer/expert range
- quantization
- backend compatibility
- expected memory footprint

## Idempotency

Every state-changing request should include:

- request id
- actor id
- target id
- precondition state where appropriate
- creation timestamp
- signature or authenticated session binding

Duplicate delivery must not duplicate ledger entries, payouts, verification decisions, or job progress.

## Privacy Tiers

Initial tiers:

- `public_compute`
- `eu_verified`
- `datacenter_only`
- `confidential_compute`

Privacy tiers are scheduling constraints, not labels for display only.

## Open Questions

- exact serialization format
- exact transport for M1
- canonical signature scheme
- shard cache eviction protocol
- model license enforcement
- precision and rounding strategy for ledger events
