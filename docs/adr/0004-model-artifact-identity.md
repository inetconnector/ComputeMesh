# ADR 0004: Model and Artifact Identity

- **Status:** Proposed
- **Date:** 2026-08-20

## Context

Human model names are mutable aliases. Distributed execution and billing need an immutable definition of exactly what was run.

## Proposed decision

Represent:

- logical `model_id`;
- immutable `model_version`;
- content-addressed artifacts;
- shard manifests that reference artifact digests;
- signatures over canonical manifest bytes.

Artifact identity uses a strong cryptographic digest selected by implementation ADR/specification.

## Consequences

- cache keys become deterministic;
- job audit can reconstruct exact artifacts;
- aliases can move without changing old jobs;
- model conversion/quantization produces a new immutable version.

## Verification

A node must reject:

- wrong digest;
- wrong size;
- incompatible manifest;
- invalid signature.

Two independent parsers must derive the same canonical digest for the same manifest before format freeze.
