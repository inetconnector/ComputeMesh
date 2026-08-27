# ComputeMesh current public status

**Current as of:** 2026-08-27

This document is the public-safe status summary. It is intentionally separate from the private `ComputeMesh-ControlPlane/STATE.md`, which contains proprietary control-plane and operational details.

## What exists today

ComputeMesh is no longer only an M0/M1 skeleton. The public repository contains real implementations for:

- authenticated provider-control sessions and Ed25519 node identity/enrollment reference state;
- a runnable public provider agent (`apps/node/provider_agent.py`) that authenticates, publishes measured profile/runtime/benchmark evidence, reconnects, and answers execution-attestation requests;
- OpenAI/Ollama-compatible gateway surfaces, model catalog handling, billing integration foundations and durable orchestration state;
- live provider registration, execution evidence, authenticated attestation collection, cancellation and recovery mechanics;
- a public reference/research scheduler and conservative two-node M1 feasibility/evidence tooling;
- a real llama.cpp shared-runtime research path, one physical trusted-lab proof, deterministic baseline/shared comparison, bound proof artifacts and controlled delay/jitter/disconnect instrumentation;
- a network sensitivity runner for real shared inference points;
- durable private-feedback delivery hooks from verified public execution outcomes;
- Windows/Linux lab setup, evidence transfer, GGUF manifest tooling, installers/appliance work, portal and updater components.

## Public/private production boundary

Production placement policy is not implemented in `services/scheduler/placement.py`. That file remains a public reference/research feasibility implementation.

The production scheduler, candidate ranking/scoring, empirical performance state, reputation/fraud policy, marketplace/pricing policy, private recovery selection and settlement policy live in the separate private `inetconnector/ComputeMesh-ControlPlane` repository. The public runtime talks to that control plane through bounded authenticated interfaces and verifies signed placement decisions before execution.

The public repository therefore remains useful for providers, protocol/runtime interoperability and reproducible research without publishing the production network's ranking/data/policy moat.

## Current live development topology

The current practical two-node live path uses:

1. a gateway/coordinator host running the public live gateway and local coordinator `llama-server`;
2. an enrolled remote provider running the public provider agent and upstream llama.cpp RPC worker;
3. private placement/recovery selection;
4. signed execution plan verification;
5. execution evidence and provider attestations;
6. durable delivery of verified outcome metrics to the private performance store.

The upstream llama.cpp RPC socket is still experimental/insecure and must not be treated as a public node security boundary. Development bring-up can carry RPC through SSH/private networking; production data-plane hardening remains required.

## What is validated vs. what is not

Validated in software/CI: contracts, identity/session/reference persistence, gateway/orchestration mechanics, placement boundary verification, provider-agent protocol path, evidence/attestation handling, feedback delivery, research runtime harnesses and controlled network instrumentation.

Validated physically: at least one narrow trusted-lab two-machine shared llama.cpp proof recorded in `state.md` for its exact hardware/model/runtime/topology.

Not yet a general production claim: broad heterogeneous two-GPU validation, controlled LAN/WAN matrix results across representative hardware/models, public/untrusted-network runtime transport, provider-enforced leases, production key storage/revocation fan-out, calibrated production performance prediction, large multi-node scheduling and full production operations/HA.

## Primary engineering entry points

- `state.md` — public historical engineering handoff/log;
- `docs/CURRENT_STATUS.md` — current public-safe status (this file);
- `ARCHITECTURE.md` — public architecture and boundaries;
- `docs/PRIVATE_CONTROL_PLANE_SPLIT.md` / `docs/PUBLIC_PRIVATE_CLASSIFICATION.md` — disclosure boundary;
- `services/orchestrator/README.md` — live orchestration/control path;
- `services/gateway/README.md` — public API/gateway path;
- `apps/node/README.md` — provider agent/node surface;
- `runtime/llama/README.md` — shared llama.cpp research/runtime evidence;
- `runtime/network/README.md` — instrumentation/transport research;
- `tests/README.md` — validation coverage;
- `setup/README.md` and `setup/README.de.md` — public lab setup/workflows.

## Immediate readiness work

The next major gate is evidence, not another public/private split: run the complete current system on the target hardware, collect reproducible LAN and WAN measurements, feed verified outcomes into the private predictor, enforce real provider resource leases, harden the provider data plane and node-key lifecycle, and then decide whether/when to widen `production_scheduling`.
