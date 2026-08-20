# ADR 0002: Select the M1 Runtime Baseline

- **Status:** Proposed
- **Date:** 2026-08-20
- **Owners:** TBD

## Context

M1 needs one narrow runtime path to prove shared inference. Supporting several frameworks before the first proof would multiply protocol, model, and failure complexity.

## Decision drivers

- Windows provider feasibility;
- heterogeneous device support;
- controllable model partitioning;
- instrumentation;
- model coverage;
- security boundary;
- transport flexibility;
- ability to prototype quickly.

## Options considered

### llama.cpp-based baseline

Useful because of broad local hardware/model support and existing remote/RPC experimentation.

Risks:

- upstream RPC is experimental and not suitable as a public security boundary;
- distributed semantics may not match ComputeMesh needs;
- heterogeneity/performance behavior must be measured.

### vLLM-based baseline

Strong multi-GPU/multi-node serving reference with tensor/pipeline/expert strategies.

Risks:

- typical deployment assumes coordinated cluster environments;
- Windows/provider-PC fit may be weaker;
- may constrain ComputeMesh transport/heterogeneity experiments.

### Minimal custom stage prototype

Gives maximum control over stage boundaries and transport.

Risks:

- highest implementation burden;
- easy to spend time rebuilding runtime functionality.

## Proposed decision

Use a **llama.cpp-oriented M1 research baseline or another equally narrow runtime path**, but do not expose its upstream RPC server as the ComputeMesh node protocol. Wrap runtime execution behind the ComputeMesh node/worker boundary.

Keep vLLM as a comparison/reference for datacenter-style distributed serving.

## Verification

Accept only after a two-node spike demonstrates:

- deterministic layer/stage placement;
- measurable activation transfer;
- output correctness;
- bounded memory;
- controllable cancellation/failure;
- workable Windows path.

If the spike fails these criteria, supersede this ADR with the next runtime candidate.
