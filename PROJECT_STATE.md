---
document_type: PROJECT_STATE
state_schema_version: "1.0"
project_state_version: 5
project_id: "PRJ-20260917-AGENTS-PLATFORM"
project_name: "ComputeMesh Agents Platform"
status: FINAL_RELEASE_CANDIDATE_VALIDATION
created_at: "2026-09-17T11:47:00+02:00"
updated_at: "2026-09-17T15:25:00+02:00"
state_owner: "ComputeMesh"
primary_goal: "Introduce a production-oriented agent platform without replacing existing MCP, memory, security or control-plane subsystems."
integrity_status: REVIEW3_MAIN_MERGED_VALIDATED
---

# Executive state snapshot

The public ComputeMesh `AgentsPlatform` branch contains the generic Agents Platform required by the implementation plan: persistent Skill Registry, automatic hybrid Skill Router, capability/side-effect-aware Tool execution, hierarchical `AGENTS.md`, resumable leased DAG/workflow execution, validation/rerouting, versioned Project State, structured scoped Memory, audit/observability hooks, feature-gated integration around the existing MCP `AgentLoop`, evaluation data and staged rollback controls.

Review 1 findings were corrected in the actual execution path rather than only in isolated components. Review 2 added permanent security/regression coverage for prompt-authority separation, request/principal/fleet-bound runtime policy, exact side-effect grants, secret egress protection, non-idempotent write retry prevention, fail-closed emergency-stop checks, cross-process DAG leases, scope-safe memory mutation, Project State CAS/locking and manifest/schema hardening.

Review 3 integrated the then-current public `main` commit `1825076ce429040a362ce484dda0f1129c1dba8b` into `AgentsPlatform` with merge commit `cd7d93614b5ed62c5a87598d6559653a696dfc99`. The incoming main change generalized the Playwright/Web Automation portal presentation and did not replace the Agents Platform security architecture. Public CI run `35226468154` passed the complete regression plus shadow, active and enforced runtime modes on that merge commit.

The private `ComputeMesh-ControlPlane/AgentsPlatform` branch also integrated its then-current `main` commit `307ab3af76ab73548e7c60044ee0f508716a7e7e` while deliberately retaining the validated Agents Platform public gitlink during conflict resolution. Private merge CI run `35226639140` passed policy tests, cross-repository enforcement and the full private regression. Once this state revision is itself public-CI green, ControlPlane must pin that exact final public SHA and re-run private CI one final time.

## Scope and authority boundary

Public ComputeMesh owns generic request contracts, skill registry/routing, DAG/workflow execution, tool capability/side-effect policy, AGENTS resolution, Project State, structured Memory, validation/provenance, audit and feature-gated runtime integration.

Private ControlPlane owns fleet/model/commercial/billing/provider/placement policy and production-specific authorization/rollout decisions. Private scoring inputs, credentials, economics and fleet internals are not copied into the public runtime. Only the minimized runtime policy envelope crosses the boundary.

Memory/context data is explicitly untrusted data. Skill guidance is subordinate workflow instruction. Neither grants tool authorization. Existing owner authorization and the emergency killswitch remain authoritative.

## Requirements status

- REQ-001 DONE: persistent, versioned, validated Skill Registry with checksums, schema compatibility and lifecycle state.
- REQ-002 DONE: hybrid Skill Router with explicit selection, abstention, ambiguity handling, dependencies/conflicts, context budgets and DAG output.
- REQ-003 DONE: capability/side-effect tool policy with preview/confirm/execute/verify, exact request/tool/argument-bound grants, egress checks, safe retry behavior and circuit breaking.
- REQ-004 DONE: hierarchical root-to-leaf `AGENTS.md` resolution.
- REQ-005 DONE: versioned Project State with atomic persistence, checkpoints, cross-process locking and stale-write/CAS protection.
- REQ-006 DONE: scoped/provenance-aware Memory v2 with expiry, conflict/supersession semantics, scope-safe deletion/derivation and legacy migration.
- REQ-007 DONE: disabled/shadow/active/enforced feature-gated rollout and documented rollback.
- REQ-008 DONE: public full regression plus explicit shadow/active/enforced CI matrix.
- REQ-009 DONE: persistent resumable DAG engine with bounded parallelism, validation, restart recovery and transactional cross-process node leasing.
- REQ-010 DONE: routing evaluation, append-only audit and permanent Review-2 security tests.
- REQ-011 DONE: private ControlPlane policy request/principal/fleet binding and real cross-repository public-runtime enforcement test.
- REQ-012 DONE: latest public/private `main` changes integrated without leaving either feature branch behind its corresponding `main` at Review-3 merge time.

## Safety decisions

- Existing `AgentLoop` and `ToolRegistry` remain the execution foundation; the Agents Platform wraps rather than silently replaces them.
- Unknown/malformed skills or tools and unavailable higher-level safety checks fail closed.
- Side-effect authorization is never inferred from skill routing or from a global boolean.
- Non-idempotent writes/execute actions are never blindly retried after ambiguous failures.
- The fleet id from an accepted private runtime policy binds the existing fleet-scoped emergency-stop key.
- Rollback does not silently destroy legacy `state.md` or legacy JSON memory.
- Agents Platform remains opt-in; production activation is a separate rollout decision from code merge.

## Validation evidence

### Review 2 baseline

Public run `35225118707` on `61166dfca2398d1072e8ac1de65035eb25ab45a8` passed full public regression and shadow/active/enforced modes. Private run `35225459727` on `c4330b97e38aa0f34b05510f1bbf0656c3a1f35e` passed exact submodule verification, compile, Ruff, private policy tests, cross-repository enforcement and full private regression while pinning that public SHA.

### Review 3 current-main integration

Public merge commit `cd7d93614b5ed62c5a87598d6559653a696dfc99` has both the previous reviewed Agents Platform head and public `main` commit `1825076ce429040a362ce484dda0f1129c1dba8b` as parents. GitHub compare reports `AgentsPlatform` ahead of public `main` and `behind_by=0`. Public CI run `35226468154` completed successfully, including:

- Agents Platform compile/contracts;
- Review-2 security/end-to-end and side-effect/killswitch tests;
- routing, DAG, health, orchestration and tool-result/egress suites;
- existing MCP regressions;
- complete `python run_all_tests.py` regression;
- runtime shadow PASS;
- runtime active PASS;
- runtime enforced PASS.

Private merge commit `7cd2a7b015825b210a5df4992e9166244743215d` has the previous reviewed private head and private `main` commit `307ab3af76ab73548e7c60044ee0f508716a7e7e` as parents. GitHub compare reports the private `AgentsPlatform` branch ahead of private `main` and `behind_by=0`. Private CI run `35226639140` completed successfully, including exact current public-pin verification, compile, Ruff, private policy tests, cross-repository enforcement and full private pytest regression.

## Risks and release status

- RISK-001 MITIGATED: backward compatibility is protected by feature flags and full regression coverage.
- RISK-002 MITIGATED: public/private policy leakage is constrained by the minimized envelope and explicit boundary tests.
- RISK-003 MITIGATED: prompt/memory authority escalation is separated and regression-tested.
- RISK-004 MITIGATED: duplicate/ambiguous side effects are constrained by leases, grants, idempotency rules and no-blind-retry behavior.
- RISK-005 MITIGATED: emergency-stop lookup failures fail closed.
- RISK-006 MITIGATED: latest `main` changes were merged and revalidated rather than ignored before release review.
- RISK-007 ACTIVE ONLY FOR BOOKKEEPING: this v5 state commit changes documentation after the green Review-3 merge commit; it must be the exact final public CI candidate before ControlPlane is repinned.

## Next actions

1. Run public Agents Platform CI on this exact v5 state commit.
2. If green, make that exact public SHA the authoritative private `ComputeMesh` gitlink and update both private pin markers plus CI pin assertion.
3. Re-run complete private CI on the exact resulting private head.
4. Confirm both feature branches remain `behind_by=0`, the private gitlink equals the final public head, and no temporary fixer workflows remain.
5. Open draft release PRs only after those invariants hold; do not merge to `main` without an explicit release instruction.

## Change log

- v1-v3: initial architecture, platform implementation and first complete validation.
- v4: Review-2 security/architecture findings closed; permanent security tests and real private-to-public enforcement validation added.
- v5: current public/private `main` changes merged into both AgentsPlatform branches, semantic submodule conflict handled deliberately, and both merge states revalidated. This state revision is the final public CI candidate before exact private re-pin and PR readiness.
