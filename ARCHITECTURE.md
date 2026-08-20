# ComputeMesh Architecture

ComputeMesh is designed as a distributed AI execution layer with a clear separation between control plane and data plane.

## System Goal

The system should make heterogeneous hardware appear as one virtual AI machine. A user selects a model; ComputeMesh decides where model shards or experts should run, how requests should flow, how failures are handled, how outputs are verified, and how providers are paid.

## Control Plane

Responsibilities:

- user and node identity
- node enrollment and authentication
- hardware discovery records
- dynamic benchmark profiles
- model and shard registry
- topology graph
- scheduler and placement planner
- job state machine
- verification policy
- reputation updates
- billing and ledger
- telemetry aggregation
- admin and operations tooling

Planned services:

- `services/gateway`: public API entry point and OpenAI-compatible endpoints
- `services/scheduler`: placement, reservation, replanning, and optimization
- `services/registry`: model manifests, shard manifests, signatures, and availability
- `services/billing`: ledger, settlement, refunds, and pricing
- `services/verification`: canary jobs, redundancy, challenges, and trust scoring
- `services/telemetry`: metrics, traces, events, and availability learning

## Data Plane

Responsibilities:

- model shard transfer
- local shard cache
- activation and KV-cache transport
- inference worker execution
- result streaming
- route update during failover
- verification trace collection

The data plane must be fast, observable, and narrow. It should execute approved inference workloads, not arbitrary customer code.

## Node

The provider node is Windows-first for V1.

Node responsibilities:

- install and update signed ComputeMesh components
- authenticate with control plane
- detect CPU, RAM, GPU, VRAM, driver, CUDA/ROCm/Metal, storage, OS, and network state
- run benchmarks
- enforce provider settings
- download and cache approved shards
- execute assigned inference stages
- report telemetry
- drain safely when user stops sharing

## Model Registry

Every model needs a manifest that describes:

- architecture
- layer count
- expert count where applicable
- quantization
- memory requirements
- KV-cache requirements
- compatible backends
- legal partitioning strategies
- shard hashes and signatures

Shards are immutable, versioned, signed, hashed, and content-addressed.

## Scheduler

The scheduler optimizes the full execution path, not individual nodes in isolation.

Initial dimensions:

- compute capability
- VRAM
- backend compatibility
- reliability
- availability
- latency
- jitter
- bandwidth
- price
- privacy tier
- failure risk
- shard locality

Network classes:

- A: ultra local, such as PCIe, NVLink, Thunderbolt/RDMA, 100/400 Gbit
- B: local LAN or same datacenter
- C: regional low-latency internet
- D: global high-latency internet

Strategy guidance:

- tensor parallelism only for ultra-fast links
- pipeline parallelism for larger contiguous blocks
- expert parallelism for MoE and internet-aware routing
- data parallelism for independent requests and batch workloads

## Failure Model

Consumer nodes may disappear at any time. Critical shards and experts need replicas or prepared replanning paths. Failover should affect only the failed route/stage where possible.

Required behavior:

- detect failed node
- stop trusting in-flight unverified result
- switch to replica or replan
- retry safely when needed
- prevent false billing
- record recovery metrics

## Persistence

PostgreSQL is the planned durable store for:

- identities
- nodes
- hardware profiles
- benchmark results
- model manifests
- job records
- job segments
- ledger entries
- payments
- reputation
- verification
- sessions
- clusters
- network metrics

Append-only or audit-sensitive records should be modeled explicitly.

## Observability

Every job must produce enough data to answer:

- which model and shard versions were used
- which nodes participated
- what the planned route was
- what the actual route was
- where time was spent
- how much traffic moved
- how verification was performed
- how cost and payout were computed
- whether any retry or replan occurred

## Initial ADRs Required

- runtime target for M1
- transport choice for initial data plane
- model manifest format
- shard hash/signature scheme
- node identity model
- telemetry event envelope
- scheduler profile schema
- billing ledger precision
