# ADR 0002: Select the M1 Runtime Baseline

- **Status:** Proposed
- **Date:** 2026-08-20
- **Last experiment design update:** 2026-08-21

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

Useful because of broad local hardware/model support and existing remote/RPC device offload.

Risks:

- upstream RPC is experimental and explicitly not a public security boundary;
- distributed semantics may not match ComputeMesh needs;
- heterogeneity/performance behavior must be measured;
- current upstream RPC has active bug reports around some cache, large-model, and advanced placement combinations.

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

Use a **llama.cpp-oriented M1 research baseline**, but do not expose the upstream RPC server as the ComputeMesh node protocol. Wrap runtime execution behind the ComputeMesh node/worker boundary.

Keep vLLM as a comparison/reference for datacenter-style distributed serving. Move to a minimal custom stage path only if the controlled llama.cpp experiment cannot satisfy the M1 proof criteria.

This ADR deliberately remains `Proposed` until real two-node evidence exists.

## First controlled experiment

`runtime/llama/rpc_spike.py` defines the first executable experiment surface.

The experiment uses current llama.cpp capabilities conservatively:

- worker RPC bind: literal loopback/RFC1918 IPv4 only;
- coordinator HTTP: `127.0.0.1` only;
- `--rpc` only toward explicitly supplied private endpoints;
- `--device` with exact names discovered from current llama.cpp;
- shared mode uses `--split-mode layer` plus explicit `--tensor-split`;
- `--fit off` prevents automatic fitting from silently changing the requested experiment;
- `--offline` prevents runtime-side model acquisition;
- `--cache-ram 0` and request `cache_prompt=false` reduce cache-related state/bug surface for the first proof;
- one server slot;
- no advanced `--override-tensor` mapping in the baseline;
- no upstream RPC cache;
- no wildcard/public assisted bind.

The harness first records a deterministic local baseline, then the explicit local+RPC split, then compares the same model/prompt using token-ID digest when available or output digest otherwise.

It records model SHA-256, llama.cpp build/version, topology, placement, model-ready time, request time, prefill/decode metrics and correctness digests. Raw prompt/output content is not persisted.

## Why the ADR is not accepted yet

The harness is only an experiment controller. It does not establish that llama.cpp RPC is the correct M1 runtime.

Acceptance still requires a real shared run demonstrating:

- at least two differing device profiles participate in one inference path;
- deterministic/reproducible placement for the measured run;
- exact output/token correctness against a local baseline for the selected probe;
- bounded memory/no crash for the selected model and split;
- measurable transfer/runtime effects;
- a controllable worker/coordinator failure path;
- workable Windows participation;
- no need to expose upstream RPC as a public/untrusted listener.

If these criteria fail, keep the evidence and supersede this ADR with vLLM or a minimal custom stage transport rather than widening an unstable RPC surface.

## Immediate verification sequence

1. Start one upstream RPC worker on a trusted private LAN using the ComputeMesh harness guardrails.
2. Run `discover` and retain the exact local/RPC device names.
3. Run the same GGUF/probe locally and save `local_baseline` result.
4. Run an explicit layer split across local + RPC devices.
5. Compare model digest, prompt digest and exact token/output digest.
6. Record prefill/decode/request ratios and host/device memory observations.
7. Repeat with deliberate worker disconnect/cancellation.
8. Add activation/transfer-size and controlled latency/jitter/loss instrumentation.
9. Accept, reject, or supersede this ADR from evidence.

## Security boundary

The upstream RPC server remains outside the ComputeMesh trust contract. Current node identity/session authentication does **not** authenticate the upstream RPC socket. Until a controlled worker boundary exists, the RPC spike is trusted-lab-only and must not be exposed to the public internet or an untrusted network.
