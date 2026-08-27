# ComputeMesh Documentation Audit — 2026-08-27

## Scope

This audit rechecked the complete documentation surface against the current public code and the implemented public/private control-plane boundary. It supersedes the initial 2026-08-20 bootstrap-only documentation review.

Reviewed classes include:

- root project/status/architecture/protocol/security documents;
- all component `README.md` files under `apps/`, `services/`, `runtime/`, `protocol/`, `setup/`, `tests/`, `tools/`, `models/`, `research/`, `deploy/` and `sdk/`;
- public/private split and trade-secret documents;
- benchmark/data/failure/privacy/test specifications;
- ADRs;
- the public `state.md` engineering history;
- public portal documentation/status surfaces;
- bilingual README/setup documentation.

The private umbrella repository was audited in parallel. Its current private authority is `ComputeMesh-ControlPlane/STATE.md`; private production-policy details must not be copied into public documentation.

## Documentation authority after this audit

### Current public status

Use:

- `docs/CURRENT_STATUS.md`
- `docs/CURRENT_STATUS.de.md`

These files are the current public-safe status source. When older documents contain historical phase labels such as “M0” or an earlier “next step”, the current-status files take precedence for **current implementation state**.

### Historical engineering record

`state.md` remains the large public engineering/handoff history. It is valuable for chronology and evidence provenance, but it is not the place for proprietary current control-plane internals.

### Target/normative design

`ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md`, `IMPLEMENTATION_PLAN.md`, specifications and ADRs remain design/history documents. Their original gate structure and accepted decision context are preserved rather than rewritten merely because implementation advanced. Current status is layered on top through the current-status documents and component READMEs.

### Private current state

The private umbrella repository's `STATE.md` is authoritative for current private placement/performance/reputation/fraud/pricing/marketplace/settlement/dispatch/outcome implementation and private next work.

## Major drift found and corrected

### 1. The project is no longer merely “M0 planning”

Several older documents still used the initial M0/M1 bootstrap language. Current code now includes a runnable provider agent, authenticated persistent provider sessions, live gateway/orchestration, private remote-first production placement, signed execution-plan verification, evidence/attestation, durable outcome feedback and real shared-runtime/network research tooling.

`SECURITY.md` and the canonical current-status documents now describe this correctly.

### 2. Public reference scheduler versus private production scheduler

The public `services/scheduler/placement.py` remains a disclosed deterministic research/reference planner. It must not be documented as the production ranking engine.

Production feasibility/ranking/selection and recovery policy live behind the private `ComputeMesh-ControlPlane` boundary. Public runtime code submits a bounded candidate/network snapshot, verifies the signed returned plan and executes it without receiving score decomposition or private policy.

### 3. Provider agent and remote provider bring-up exist

The public repository contains `apps/node/provider_agent.py`. The private umbrella contains SSH operator tooling that enrolls a remote key without extracting its private half and a one-command provider runtime path that captures real evidence, starts remote-loopback llama.cpp RPC, creates secure development tunnels and starts the public provider agent.

Documentation must no longer imply that provider operation is only a future UI concept or only the old manual lab path.

### 4. Measured feedback exists

Verified public execution measurements can be durably delivered to the private outcome/performance path. Documentation must distinguish this from a future generic telemetry service and must not claim true TTFT when the non-streaming runtime has not directly measured it.

### 5. Standalone service names versus implemented foundations

Some component READMEs used “planned component / no implementation” even though their responsibilities are partly implemented elsewhere. These are now distinguished explicitly:

- standalone registry service: still future, but model manifests, artifact identity and live model catalog foundations exist;
- standalone telemetry service: still future, but bounded evidence/metrics/network observations and private measured feedback exist;
- standalone public verification/reputation service: still future, but execution attestation/evidence verification exists publicly and production reputation/fraud state is private;
- `apps/admin`, `apps/dashboard`, `apps/desktop`, public SDK, vLLM adapter and custom CUDA research component remain future-specific surfaces unless/until their actual entry points are implemented.

### 6. Upstream llama.cpp RPC security wording

All current documentation must preserve the invariant that upstream llama.cpp RPC is experimental/insecure and is not the ComputeMesh provider security boundary. Trusted networking/SSH tunnelling is a development containment mechanism, not proof that RPC itself is production-safe.

### 7. Private state-document correction

Before this audit the private umbrella repository did **not** have a `STATE.md`. A private canonical `STATE.md` has now been added. The public `state.md` remains separate and public-safe.

## Documents intentionally preserved as historical/design baselines

The following classes are not rewritten merely to replace every old phase word:

- accepted/proposed ADRs, because they record decision context;
- `IMPLEMENTATION_PLAN.md`, because its gates/hypotheses remain useful as the original execution plan;
- architecture/protocol target sections that remain normative design goals;
- historical measurements/evidence in `state.md`;
- the original lab setup/evidence procedures that remain valid and reproducible.

Where their old “current phase” language can mislead, `docs/CURRENT_STATUS.md` is the explicit current-state override.

## Documents verified as still correctly future/planned

At this audit, the following specific surfaces remain genuinely future/planned and their status should not be inflated:

- `apps/admin/` dedicated admin application;
- `apps/dashboard/` dedicated customer/provider dashboard application;
- `apps/desktop/` dedicated end-user desktop client;
- `sdk/` public client-library package;
- `runtime/vllm/` vLLM integration;
- `runtime/cuda/` custom CUDA research implementation beyond existing benchmark/runtime use.

Other existing portal/appliance/dashboard code must not be mislabeled as those exact planned components.

## Current engineering priority reflected in documentation

The highest-value next work is physical system validation and hardening, not another architecture split:

```text
current umbrella stack
-> real enrolled target providers
-> full gateway/private-placement/shared-runtime/attestation/feedback proof
-> controlled LAN matrix
-> WAN/two-site matrix
-> private predictor calibration
-> provider-enforced resource leases
-> production-safe data plane and node-key/session lifecycle
-> adversarial/system validation
-> wider production scheduling
```

## Maintenance rule

Every feature PR that changes a public interface, trust boundary, operator entry point, readiness claim or component implementation status must update the nearest component README and, when it changes system-level truth, `docs/CURRENT_STATUS.md` (plus the German counterpart when user-facing wording changes). Private production-policy changes update private `STATE.md`/architecture without leaking proprietary internals into this repository.
