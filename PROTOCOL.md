# ComputeMesh Protocol Specification — Draft

**Status:** Draft v0.2, not wire-stable  
**Compatibility promise:** none until an explicit protocol v1 freeze  
**Scope:** public API extensions, node control protocol, data-plane framing, manifests, errors, retries, and version negotiation

## 1. Design principles

The protocol must be:

- explicitly versioned;
- authenticated;
- replay-safe for state changes;
- bounded in message size;
- cancellable;
- observable;
- tolerant of duplicate delivery;
- forward-compatible where practical;
- strict about unknown security-sensitive fields;
- independent of one runtime implementation.

The control plane favors correctness and explicit state. The data plane favors low overhead and backpressure.

## 2. Versioning

Every connection begins with protocol negotiation.

Required concepts:

- `protocol_major`: incompatible wire/semantic changes;
- `protocol_minor`: backward-compatible capabilities;
- `agent_version`;
- `runtime_versions`;
- `capabilities[]`.

Rules:

- peers with different unsupported major versions MUST reject the session;
- minor-version features MUST be capability-negotiated;
- a sender MUST NOT assume a feature from software version alone;
- the negotiated feature set is recorded with each job.

## 3. Common control envelope

Every state-changing control message should carry:

```json
{
  "protocol_major": 0,
  "protocol_minor": 2,
  "message_type": "JobAssignment",
  "request_id": "uuid",
  "correlation_id": "uuid",
  "actor_id": "node-or-service-id",
  "target_id": "node-or-job-id",
  "issued_at": "RFC3339 timestamp",
  "expires_at": "RFC3339 timestamp",
  "expected_revision": 17,
  "payload": {}
}
```

Semantics:

- `request_id` is the idempotency key;
- `correlation_id` links a workflow;
- `expires_at` prevents delayed command replay;
- `expected_revision` protects state transitions from stale writers;
- authentication binds the session/peer identity to `actor_id`.

Signatures MAY additionally bind selected high-value records such as manifests and release metadata.

## 4. Error model

Errors are machine-readable.

```json
{
  "code": "RESERVATION_EXPIRED",
  "category": "conflict",
  "retryable": true,
  "message": "human readable diagnostic",
  "details": {},
  "request_id": "uuid"
}
```

Initial categories:

- `invalid_argument`;
- `unauthenticated`;
- `forbidden`;
- `not_found`;
- `conflict`;
- `resource_exhausted`;
- `deadline_exceeded`;
- `temporarily_unavailable`;
- `incompatible`;
- `integrity_failure`;
- `internal`.

The `retryable` flag is advisory; retry policy is also determined by operation semantics.

## 5. Idempotency and retries

Operations are classified:

### Read-only

Safe to retry freely within deadline.

### Idempotent mutation

Requires `request_id`. Duplicate delivery returns the original effect/result.

Examples:

- availability update;
- reservation release;
- drain request;
- job cancellation.

### Exactly-once business effect over at-least-once delivery

Financial and job-state operations use durable deduplication.

Examples:

- ledger posting;
- provider credit;
- verification decision;
- transition to `COMPLETED`.

The network does not provide true exactly-once delivery. The application provides exactly-once **effect** through identifiers, revisions, and durable constraints.

## 6. Public API

Initial compatibility surface:

```text
POST /v1/chat/completions
POST /v1/responses
POST /v1/embeddings
GET  /v1/models
```

OpenAI-compatible behavior should remain standards-compatible. ComputeMesh policy must be namespaced rather than silently reinterpret existing fields.

Example request extension:

```json
{
  "model": "example-model",
  "input": "Hello",
  "computemesh": {
    "privacy_tier": "public_compute",
    "latency_class": "interactive",
    "max_budget_minor": 250,
    "currency": "EUR",
    "deadline_ms": 15000,
    "preferred_regions": ["eu-central"],
    "verification_policy": "standard"
  }
}
```

Server response metadata MAY expose:

- job ID;
- execution mode;
- approximate region class;
- measured latency;
- usage;
- charge;
- verification status.

Provider identities MUST NOT be exposed unless policy explicitly allows it.

## 7. Node session lifecycle

```text
CONNECT
  -> Hello
  -> Authenticate
  -> CapabilityNegotiation
  -> ProfileSync
  -> BenchmarkStatus
  -> READY
  -> heartbeat / availability / reservations / jobs
  -> DRAINING
  -> DISCONNECT
```

A node is not schedulable until identity, capabilities, policy, profile freshness, and required benchmark status are accepted.

## 8. Node control messages

### `NodeHello`

Carries:

- protocol versions;
- node agent version;
- OS/platform;
- stable node ID if enrolled;
- supported authentication methods;
- capabilities.

No scheduling decisions are made from `NodeHello` alone.

### `NodeAuthenticate`

Completes node authentication and session binding.

### `NodeProfileUpdate`

Includes:

- hardware inventory;
- runtime capabilities;
- memory capacity;
- local artifact cache summary;
- provider policy;
- thermal/power limits;
- profile revision.

### `BenchmarkReport`

Includes:

- benchmark schema version;
- hardware/profile revision;
- runtime version;
- test conditions;
- metrics;
- timestamp;
- run ID;
- integrity metadata.

### `AvailabilityUpdate`

Includes:

- available devices;
- resource limits;
- planned availability window;
- provider min-price policy if enabled;
- drain status.

### `ReserveCapacity`

Control plane asks the node to hold capacity for a short lease.

Fields:

- reservation ID;
- resource request;
- model/stage compatibility requirement;
- memory budget;
- lease expiry;
- quoted price terms.

### `ReservationAccepted` / `ReservationRejected`

Acceptance returns reservation revision and expiry.

### `CommitReservation`

Binds an accepted lease to a concrete job and stage.

### `JobAssignment`

Contains:

- job ID;
- placement revision;
- model manifest digest;
- shard/stage references;
- runtime;
- execution policy;
- stream endpoints/credentials;
- deadlines;
- verification requirements.

### `ShardPrepare`

Requests verified local preparation of artifacts.

### `ShardReady`

Returns:

- artifact digests;
- verification result;
- loaded/cached state;
- expected memory use;
- preparation time.

### `ExecuteSegment`

Starts or advances a defined inference segment. It MUST refer to an existing committed assignment.

### `SegmentResult`

Reports execution output metadata, not arbitrary provider-defined data.

### `VerificationTrace`

Carries only the trace fields requested by the verification policy.

### `CancelJob`

Cancellation is idempotent. It includes a cancellation reason and cutoff policy.

### `DrainRequest`

Stops new reservations and transitions the node toward a safe idle state.

### `FailureReport`

Structured failure:

- job/stage;
- failure code;
- runtime state;
- retryability signal;
- last safe checkpoint reference if any;
- resource metrics;
- no prompt/output by default.

## 9. Heartbeats and liveness

Heartbeats distinguish:

- session alive;
- node schedulable;
- current capacity;
- current reservation/job revisions.

A missed heartbeat does not instantly prove failure. The control plane uses configurable suspicion and failure timeouts.

The thresholds are test parameters, not hard-coded protocol constants.

## 10. Data-plane streams

The transport implementation is an ADR decision. The protocol distinguishes logical stream classes independent of transport:

- `artifact`;
- `activation`;
- `runtime_control`;
- `result`;
- `kv_migration`;
- `verification`.

Each stream is bound to:

- job ID;
- placement revision;
- source/target stage;
- stream type;
- sequence or chunk position;
- integrity policy;
- deadline.

## 11. Backpressure

A receiver MUST be able to signal bounded capacity. Senders MUST NOT accumulate unbounded activations or result buffers.

The runtime reports:

- maximum in-flight frames;
- maximum frame bytes;
- preferred chunk size;
- queue depth.

Backpressure behavior is benchmarked because it directly affects pipeline bubbles and memory pressure.

## 12. Activation transfer

Activation frames need:

- tensor metadata;
- dtype/quantization if transformed;
- shape;
- logical token/batch position;
- stage transition ID;
- payload digest or transport-integrity binding;
- compression/encoding capability if used.

The protocol should avoid serializing high-level framework objects directly.

## 13. KV migration

KV migration is a separate stream class because it is large and semantically different from normal per-token stage transfer.

Required uses include experimentation with:

- node replacement;
- stage migration;
- checkpointing;
- session relocation.

A runtime MAY declare KV migration unsupported. The scheduler must then treat that stage as restart-only on failure.

## 14. Artifact protocol

Artifacts are addressed by digest.

A prepare request includes:

- manifest digest;
- artifact digest;
- expected byte size;
- allowed sources;
- signature metadata.

The node MUST verify digest before declaring the artifact ready.

Partial downloads use resumable ranges/chunks only if integrity remains unambiguous.

## 15. Manifest schemas

### Model manifest

Minimum fields:

```yaml
schema_version: 1
model_id: org/model
model_version: immutable-version
architecture: transformer-family
license:
  id: ...
  source: ...
runtime_compatibility:
  - runtime: llama
    min_version: ...
quantizations: [...]
partitioning:
  allowed:
    - contiguous_layers
    - experts
artifacts: [...]
```

### Shard manifest

```yaml
schema_version: 1
shard_id: sha256:...
model_version: ...
content_digest: sha256:...
size_bytes: 123
range:
  layers: [0, 7]
quantization: ...
runtime_compatibility: [...]
memory_estimate_bytes: ...
signature: ...
```

The exact serialization format remains an ADR. The semantic fields should stabilize before the wire encoding.

## 16. Authentication and authorization

The protocol needs distinct identities for:

- user/API principal;
- node;
- service;
- release signer;
- artifact signer.

Authentication answers **who** the peer is. Authorization answers **what** that peer may do.

A node session MUST NOT gain generic filesystem, shell, process-launch, or arbitrary-code permissions through protocol extensibility.

## 17. Replay protection

Protection uses a combination of:

- authenticated session;
- request ID;
- expiry;
- revision/precondition;
- durable deduplication for high-value mutations.

A timestamp alone is insufficient replay protection.

## 18. Cancellation and deadlines

Every job has a client deadline and internal phase deadlines.

Cancellation propagates:

```text
client -> gateway -> orchestrator -> affected reservations/nodes
```

Cancellation is best-effort for already-running device kernels but must stop new billable work as soon as safely possible.

## 19. Protocol security limits

Transport encryption protects data in transit. It does not protect plaintext after it reaches a provider-controlled process.

A privacy tier that promises confidential execution requires a separate trusted-execution/attestation mechanism; TLS or QUIC alone is not sufficient.

## 20. M0 decisions still required

ADRs must select:

- serialization format;
- control transport;
- M1 data transport;
- authentication/key enrollment;
- artifact signatures;
- manifest canonicalization;
- stream integrity method;
- heartbeat/lease defaults;
- ledger unit representation.
