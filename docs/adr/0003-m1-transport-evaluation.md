# ADR 0003: M1 Control and Data Transport Evaluation

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

Control traffic and tensor/activation traffic have different requirements. Choosing one transport for every message before measurement would couple unrelated concerns.

## Decision

Treat them as separate logical planes.

For M1 evaluate:

- reliable RPC/streaming stack for control;
- gRPC streaming and a QUIC-based data path as experiment candidates;
- transport-neutral application stream semantics in `PROTOCOL.md`.

Do not encode scheduler/job semantics directly into a transport library API.

## Decision drivers

- authentication;
- Windows support;
- streaming/backpressure;
- cancellation;
- connection recovery;
- small-frame latency;
- large-frame throughput;
- instrumentation;
- implementation maturity.

## Verification

Compare under:

- LAN;
- RTT injection;
- jitter;
- packet loss;
- reconnection;
- concurrent streams.

Record application-level p50/p95 latency and throughput, not only raw socket benchmarks.

## Revisit trigger

A transport that cannot meet protocol security or backpressure requirements is rejected even if its raw throughput is higher.
