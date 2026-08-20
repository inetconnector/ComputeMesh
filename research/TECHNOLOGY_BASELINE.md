# Distributed Inference Technology Baseline

**Checked:** 2026-08-20  
**Purpose:** record what ComputeMesh should learn from existing systems without assuming they solve the same problem.

## vLLM

Useful reference for:

- tensor parallel inference;
- pipeline parallel inference;
- multi-node serving;
- expert/MoE parallelism;
- high-throughput serving.

Architectural lesson:

vLLM is a strong baseline for coordinated clusters. ComputeMesh should compare its own plans against this style of deployment, but consumer WAN nodes introduce churn, heterogeneity, NAT/security, and economic constraints beyond the normal cluster assumption.

## llama.cpp / ggml RPC

Useful reference for:

- broad local hardware support;
- model offload;
- remote device experimentation;
- content cache concepts;
- simple distributed inference experiments.

Security lesson:

The upstream RPC functionality is explicitly experimental and warns against open-network exposure. ComputeMesh must not expose that upstream RPC service as its provider security boundary.

## Petals

Useful reference for:

- decentralized layer/block serving;
- routing across distributed peers;
- lessons from internet-scale transformer inference;
- incentives/reliability research.

Questions for ComputeMesh:

- real observed latency under modern models;
- churn behavior;
- verification/trust;
- current maintenance/activity;
- model compatibility.

## exo

Useful reference for:

- device discovery;
- local-cluster cooperative inference;
- heterogeneous device orchestration concepts;
- user-facing “cluster as one resource” UX ideas.

Questions:

- topology assumptions;
- supported runtimes/models;
- failure semantics;
- WAN versus local-network focus.

## NCCL

Useful reference for:

- optimized GPU collectives on high-performance intra/inter-node links.

Architectural lesson:

NCCL-oriented tensor parallelism is a datacenter/tightly-coupled baseline. ComputeMesh should not extrapolate its performance to arbitrary WAN links.

## Ray / DeepSpeed

Useful reference for:

- distributed process/job coordination;
- cluster orchestration;
- model parallel training/inference techniques.

ComputeMesh should borrow concepts selectively rather than make provider PCs general Ray/cluster workers.

## Evaluation rule

For every external technology, record:

- exact version/commit;
- supported OS/device;
- trust/security assumptions;
- topology assumptions;
- failure behavior;
- model/runtime constraints;
- benchmark conditions;
- license.

An upstream feature is not a ComputeMesh feature until integrated behind ComputeMesh's protocol and security boundaries.
