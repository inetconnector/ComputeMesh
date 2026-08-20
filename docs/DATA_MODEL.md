# ComputeMesh Canonical Data Model

**Status:** Draft v0.1

This document defines semantic entities. It is not yet a physical PostgreSQL schema.

## Principles

- distinguish identity from mutable profile;
- distinguish planned placement from execution attempt;
- distinguish metering from ledger;
- immutable facts are not overwritten;
- mutable resources use revisions;
- monetary data uses integer fixed units, never floating-point;
- timestamps are UTC with explicit representation;
- every cross-service event has stable identity.

## Core entities

### Principal

Represents a user, service, or organization identity.

Key concepts:

- `principal_id`;
- type;
- status;
- authentication bindings.

### Node

Stable provider-node identity.

Fields include:

- `node_id`;
- owner principal;
- enrollment status;
- trust state;
- creation/revocation timestamps.

Hardware changes do not create a new node automatically.

### Device

A schedulable compute device attached to a node.

- device ID scoped to node;
- backend;
- memory;
- capabilities;
- current enabled state.

### NodeProfile

Versioned snapshot:

- profile revision;
- inventory;
- runtime capabilities;
- provider limits;
- benchmark references;
- update time.

### BenchmarkRun

Immutable measurement set tied to profile/runtime/test conditions.

### NetworkObservation

Directional observation between endpoints/regions.

### Model

Logical model identity.

### ModelVersion

Immutable runnable version/configuration.

### Artifact

Content-addressed byte object.

### Shard

Semantic model partition backed by one or more artifacts.

### CapacityOffer

Current node-advertised available capacity and provider policy.

### Reservation

Short-lived lease of resources.

States:

```text
OFFERED/CANDIDATE -> LEASED -> COMMITTED -> ACTIVE -> RELEASED
                                  \-> EXPIRED
```

### Job

Customer-visible request lifecycle.

### Placement

Immutable revisioned execution plan for a job.

A replan creates a new placement revision.

### Stage

Logical portion of a placement.

### Attempt

One actual execution attempt for a stage/job revision.

Retries are new attempts, not mutation of history.

### VerificationPolicy

Policy attached to job/attempt.

### VerificationResult

Immutable outcome/evidence.

### ReputationEvidence

Individual signed/auditable trust evidence. Aggregate reputation is derived.

### MeteringEvent

Immutable measurement used for financial calculation.

Examples:

- accepted GPU milliseconds;
- accepted bytes;
- verified stage completion;
- platform fee basis.

### LedgerEntry

Append-only financial accounting entry.

Use double-entry accounting semantics.

### Settlement

External payout/payment aggregation referencing ledger balances.

## Job state

Recommended high-level states:

```text
CREATED
-> VALIDATING
-> PLANNING
-> RESERVING
-> PREPARING
-> RUNNING
-> VERIFYING
-> COMPLETED
-> SETTLED
```

Terminal/alternate:

- CANCELLED;
- FAILED;
- REFUNDED.

`RETRY` and `REPLAN` are better represented as transitions/actions plus attempts/placement revisions rather than permanent job states.

## Revision rules

Mutable entities that participate in distributed state transitions should have monotonic revision:

- node profile;
- capacity offer;
- reservation;
- job;
- placement.

A stale writer cannot replace a newer revision.

## Idempotency

Store processed idempotency keys for:

- job creation;
- reservation commit/release;
- cancellation;
- verification decision;
- metering acceptance;
- ledger posting.

## Money

No floating-point.

Example semantic type:

```text
Money {
  currency: "EUR"
  minor_units: int64
}
```

For sub-cent internal metering, use a separately named high-resolution unit selected by ADR, then convert to settlement currency deterministically.

## Deletion and retention

Financial/audit records may need longer retention than telemetry. Privacy-sensitive telemetry should use short documented retention and deletion policy.

Deletion of a user account should not silently delete records legally required for financial reconciliation; use pseudonymization/retention policy as legally appropriate.
