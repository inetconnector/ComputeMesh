# ComputeMesh documentation index

**Audit date:** 2026-08-27  
**Purpose:** authoritative map of the public documentation surface after the full documentation audit.

`docs/CURRENT_STATUS.md` (and `docs/CURRENT_STATUS.de.md`) is the current public-safe status source. Historical plans/ADRs are not silently rewritten into present-tense implementation claims; component READMEs describe the nearest actual implementation. Private production-policy state belongs in the private `ComputeMesh-ControlPlane/STATE.md` and must not be copied here.

## Authority levels

- **CURRENT** — intended to describe current implementation/operation; update with relevant code changes.
- **NORMATIVE/TARGET** — architecture/specification/design contract; current implementation may be a subset.
- **HISTORICAL** — engineering chronology/decision context; preserve evidence and dates.
- **PLANNED** — a specific component that genuinely does not yet have the claimed production entry point.
- **LEGAL/POLICY** — must not be casually changed as technical status text.

## Root documentation

| Document | Classification | Audit result |
| --- | --- | --- |
| `README.md` | CURRENT + historical overview | reviewed; detailed legacy M0/M1 material remains useful, but current status/priority statements are superseded by `docs/CURRENT_STATUS.md` where they conflict |
| `README.de.md` | CURRENT + historical overview | reviewed; same authority rule as English README; current German status lives in `docs/CURRENT_STATUS.de.md` |
| `ARCHITECTURE.md` | NORMATIVE/TARGET | reviewed; target invariants remain useful; older implementation-phase wording is not the current status source |
| `IMPLEMENTATION_PLAN.md` | HISTORICAL/TARGET PLAN | reviewed; original hypotheses/gates remain useful; the old `Current phase: M0` line is historical and is superseded by current-status docs |
| `PROTOCOL.md` | NORMATIVE/TARGET | reviewed; still explicitly draft/not wire-stable; many contracts now have implementations but no v1 freeze exists |
| `SECURITY.md` | CURRENT POLICY | corrected in this audit to reflect active pre-production code and current trust boundaries |
| `THREAT_MODEL.md` | NORMATIVE/TARGET | reviewed; threat assumptions remain valid; private production-policy details stay private |
| `CONTRIBUTING.md` | CURRENT PROCESS | reviewed; no system-status authority |
| `state.md` | HISTORICAL | reviewed as public engineering/evidence chronology; not the private current-state source |

## Current status and documentation governance

| Document | Classification | Audit result |
| --- | --- | --- |
| `docs/CURRENT_STATUS.md` | CURRENT | added in this audit; canonical public-safe status |
| `docs/CURRENT_STATUS.de.md` | CURRENT | added in this audit; German canonical public-safe status |
| `docs/DOCUMENTATION_REVIEW.md` | CURRENT GOVERNANCE | replaced with the 2026-08-27 full audit |
| `docs/DOCUMENTATION_INDEX.md` | CURRENT GOVERNANCE | this complete authority map |
| `DOCS_CHANGESET.json` | HISTORICAL/AUTOMATION METADATA | reviewed; not a current architecture authority |

## Architecture/security/specification documents

| Document | Classification | Audit result |
| --- | --- | --- |
| `docs/BENCHMARK_SPEC.md` | NORMATIVE/TARGET | reviewed; benchmark/evidence principles remain applicable |
| `docs/DATA_MODEL.md` | NORMATIVE/TARGET | reviewed; target domain model remains applicable |
| `docs/FAILURE_SEMANTICS.md` | NORMATIVE/TARGET | reviewed; retry/replan/billing-neutrality semantics remain applicable |
| `docs/PRIVACY_TIERS.md` | NORMATIVE/TARGET | reviewed; confidentiality limitations remain required |
| `docs/TEST_MATRIX.md` | NORMATIVE/TARGET | reviewed; broader physical/adversarial matrix still open |
| `docs/PRIVATE_CONTROL_PLANE_SPLIT.md` | CURRENT ARCHITECTURE BOUNDARY | reviewed; split is implemented; private implementation details remain outside public repo |
| `docs/PUBLIC_PRIVATE_CLASSIFICATION.md` | CURRENT DISCLOSURE POLICY | reviewed; still authoritative for public/private classification |
| `docs/IP_AND_TRADE_SECRET_POLICY.md` | LEGAL/POLICY | reviewed for architectural consistency; do not treat as legal advice or rewrite casually |
| `docs/ORCHESTRATED_INFERENCE.md` | NORMATIVE/IMPLEMENTATION GUIDE | reviewed against current orchestrator/live path |
| `docs/MINING_RIG_APPLIANCE.md` | IMPLEMENTATION GUIDE | reviewed; appliance-specific status must not be generalized to whole network readiness |
| `docs/MONETIZATION_GUIDE.md` | PRODUCT/ECONOMICS GUIDE | reviewed; public billing mechanics and private production pricing policy must remain distinguished |
| `docs/OLLAMA_TEASER_GUIDE.md` | DEMO/OPERATIONS GUIDE | reviewed; demo paths must not be represented as production distributed-runtime proof |
| `docs/SEARCH_INDEXING.md` | OPERATIONS GUIDE | reviewed; search-indexing procedure does not establish product readiness |
| `docs/WEB_PORTAL_SPEC.md` | TARGET/PORTAL SPEC | reviewed; marketing claims must defer to current-status evidence |
| `docs/walkthrough.md` | WALKTHROUGH | reviewed; historical/manual steps remain useful where explicitly labeled |

## ADRs

All files under `docs/adr/` are **HISTORICAL/NORMATIVE DECISION RECORDS**. They were reviewed as a set and are intentionally preserved rather than rewritten to erase their original decision context:

- `0000-adr-template.md`
- `0001-bootstrap-from-blueprint.md`
- `0002-m1-runtime-baseline.md`
- `0003-m1-transport-evaluation.md`
- `0004-model-artifact-identity.md`
- `0005-node-identity.md`
- `0006-telemetry-envelope.md`
- `0007-ledger-units.md`

A later implementation does not retroactively change what an ADR recorded; follow-up ADRs should supersede decisions when needed.

## Public application READMEs

| Document | Classification | Audit result |
| --- | --- | --- |
| `apps/node/README.md` | CURRENT | runnable public provider-agent path exists; reviewed against provider-control/attestation implementation |
| `apps/admin/README.md` | PLANNED SPECIFIC APP | dedicated admin app remains planned; existing gateway admin endpoints are not this application |
| `apps/dashboard/README.md` | PLANNED SPECIFIC APP | dedicated account dashboard remains planned; appliance dashboard/portal are separate surfaces |
| `apps/desktop/README.md` | PLANNED SPECIFIC APP | dedicated end-user desktop client remains planned; provider/node installers are separate |

## Service READMEs

| Document | Classification | Audit result |
| --- | --- | --- |
| `services/gateway/README.md` | CURRENT | already reflects live shared serving, private placement and billing paths |
| `services/orchestrator/README.md` | CURRENT | already reflects durable/live orchestration, private placement and feedback |
| `services/identity/README.md` | CURRENT + READINESS LIMITS | reviewed; reference identity exists, production key/session hardening remains open |
| `services/scheduler/README.md` | CURRENT RESEARCH/REFERENCE | reviewed; public scheduler is research/reference, not production ranking |
| `services/billing/README.md` | CURRENT FOUNDATION | reviewed; ledger/Stripe foundations exist; private production economics remain private |
| `services/registry/README.md` | CURRENT FOUNDATION + FUTURE SERVICE | corrected in this audit: manifest/catalog foundations exist, standalone production registry remains future |
| `services/telemetry/README.md` | CURRENT FOUNDATION + FUTURE SERVICE | corrected in this audit: evidence/metrics/feedback exist, standalone telemetry platform remains future |
| `services/verification/README.md` | CURRENT FOUNDATION + PRIVATE POLICY | corrected in this audit: public attestation/evidence verification exists; production reputation/fraud is private |

## Runtime/research documentation

| Document | Classification | Audit result |
| --- | --- | --- |
| `runtime/llama/README.md` | CURRENT RESEARCH RUNTIME | reviewed; accurately states trusted-lab proof and RPC security limitations |
| `runtime/network/README.md` | CURRENT RESEARCH TOOL | reviewed; delay/jitter/disconnect capabilities and packet-loss limitation remain accurate |
| `runtime/vllm/README.md` | PLANNED | reviewed; still a future comparison/integration path |
| `runtime/cuda/README.md` | PLANNED RESEARCH | reviewed; custom CUDA work remains intentionally deferred pending evidence |
| `research/README.md` | RESEARCH | reviewed; not a product-readiness authority |
| `research/TECHNOLOGY_BASELINE.md` | HISTORICAL/RESEARCH BASELINE | reviewed; preserve dated technology assumptions/evidence |

## Protocol/model/setup/test/tool documentation

| Document | Classification | Audit result |
| --- | --- | --- |
| `protocol/README.md` | CURRENT CONTRACT GUIDE | reviewed against implemented control/session contracts |
| `protocol/schemas/README.md` | CURRENT SCHEMA GUIDE | reviewed; schema-specific authority |
| `models/README.md` | CURRENT/TARGET MODEL GUIDE | reviewed; artifact identity limits remain important |
| `setup/README.md` | CURRENT LAB OPERATIONS | reviewed; historical/manual lab workflows remain supported |
| `setup/README.de.md` | CURRENT LAB OPERATIONS | reviewed; German lab workflow retained |
| `tests/README.md` | CURRENT VALIDATION GUIDE | reviewed; system/physical gaps remain distinct from unit/integration CI |
| `tools/benchmark/README.md` | CURRENT BENCHMARK GUIDE | reviewed; real measurement and GGUF tooling remain current |
| `deploy/README.md` | CURRENT/EXPERIMENTAL DEPLOYMENT GUIDE | reviewed; deployment artifacts do not imply production network readiness |
| `sdk/README.md` | PLANNED | reviewed; standalone public SDK remains future |

## Public portal documentation/status surfaces

The portal HTML was included in the audit even though it is not Markdown:

- `portal/docs.html`
- `portal/status.html`
- related portal landing/benchmark/download surfaces

Some portal copy predates the current evidence boundary and uses stronger product-language than the repository can currently substantiate (for example generic “public alpha active”, “full drop-in”, universal provider readiness or fixed performance assertions). Such copy is **not** an engineering source of truth. Until it is separately normalized, technical/readiness claims must defer to `docs/CURRENT_STATUS.md` and measured evidence. Legal pages (`privacy`, `terms`, `impressum`) are a separate legal/policy surface and were not rewritten as technical documentation.

## Maintenance rule

When code changes implementation status, a trust boundary, an operator command or a public claim:

1. update the nearest component README;
2. update `docs/CURRENT_STATUS.md` and `.de.md` if system-level public status changed;
3. update private `STATE.md` if private control-plane state changed;
4. add/supersede an ADR rather than rewriting historical decision context;
5. never copy private production scoring/data/policy into public docs merely for completeness.
