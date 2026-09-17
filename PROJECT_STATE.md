---
document_type: PROJECT_STATE
state_schema_version: "1.0"
project_state_version: 4
project_id: "PRJ-20260917-AGENTS-PLATFORM"
project_name: "ComputeMesh Agents Platform"
status: FINAL_PUBLIC_STATE_VALIDATION
created_at: "2026-09-17T11:47:00+02:00"
updated_at: "2026-09-17T15:00:00+02:00"
state_owner: "ComputeMesh"
primary_goal: "Introduce a production-oriented agent platform without replacing existing MCP, memory, security or control-plane subsystems."
integrity_status: REVIEW2_VALIDATED
---

# Executive state snapshot

The public ComputeMesh `AgentsPlatform` branch now contains the generic agent-runtime layer required by the implementation plan and the second security/architecture review: persistent skill registry, automatic hybrid skill router, capability/side-effect tool policy, hierarchical `AGENTS.md` resolution, resumable leased DAG/workflow execution, versioned project state, structured scoped memory, audit/observability hooks, feature-gated integration around the existing MCP `AgentLoop`, routing evaluation, staged rollback documentation and permanent review-2 security regression tests.

The private `ComputeMesh-ControlPlane/AgentsPlatform` branch contains private policy/rollout adapters only and preserves the public/private responsibility boundary. Private policy decisions are request-, principal- and fleet-bound before the public runtime receives a minimized envelope. Existing MCP owner authorization and emergency killswitch behavior remain authoritative.

Review 2 closed the principal execution-path gaps identified after the first implementation pass: active requests now traverse routing and persistent DAG execution; skill instructions and memory data are separated by authority; memory remains untrusted data; tool grants are bound to request, tool and argument hash; egress secrets fail closed; non-idempotent writes are never blindly retried; workflow nodes use cross-process leases; memory supersession/deletion/derivation is scope-safe; project-state writes use locking/CAS; manifest schemas fail closed; runtime policy reaches the existing fleet-scoped killswitch key; and a killswitch-check failure blocks execution instead of silently continuing.

## Scope

Public ComputeMesh owns generic runtime contracts and reusable implementations for request envelopes, skill registry/routing, DAG/workflow execution, tool capability/side-effect policy, AGENTS scope resolution, project state, structured memory, validation/provenance, audit and feature-gated integration.

Private ControlPlane owns fleet/model/commercial/billing/provider/placement policy and production-specific authorization/rollout decisions. Private scoring inputs, economics, credentials and fleet internals are not copied into the public runtime.

## Requirements

- REQ-001 DONE: persistent, versioned, validated skill registry with checksums, supported manifest schema versions and lifecycle state.
- REQ-002 DONE: request envelope plus hybrid skill routing with abstention, ambiguity handling, dependencies/conflicts, context budget and DAG output.
- REQ-003 DONE: capability/side-effect policy in front of the existing ToolRegistry with preview/confirm/execute/verify, request-bound authorization grants, idempotency, safe retry behavior, circuit breaking and egress-secret checks.
- REQ-004 DONE: hierarchical AGENTS rule discovery and root-to-leaf scope resolution.
- REQ-005 DONE: canonical, versioned, atomic project-state persistence with checkpoints, stale-write detection and cross-process write locking.
- REQ-006 DONE: scoped/provenance-aware structured memory with expiry, conflict/supersession behavior, scope-safe deletion/derivation and legacy JSON migration.
- REQ-007 DONE: feature-gated runtime facade and documented staged rollout/rollback path.
- REQ-008 DONE: public component/security/MCP/full regression gates pass in shadow, active and enforced runtime modes.
- REQ-009 DONE: persistent resumable DAG/workflow engine with bounded parallelism, validation, resume, lease-based cross-process duplicate-execution protection and legacy interrupted-state compatibility.
- REQ-010 DONE: routing evaluation dataset, append-only observable decision audit and permanent review-2 regression coverage.
- REQ-011 DONE: private ControlPlane policy is request/principal/fleet bound and validated end-to-end against the pinned public runtime.

## Decisions

- DEC-001: Extend `services/mcp` instead of introducing a parallel agent loop.
- DEC-002: Keep the existing MCP `ToolRegistry` as the concrete execution backend and place capability/side-effect policy in front of it.
- DEC-003: Use SQLite for durable skill, memory, workflow and execution-policy state; use atomic versioned project-state snapshots/checkpoints for resumability.
- DEC-004: Keep private fleet/model/billing/provider/placement policy out of public generic runtime code.
- DEC-005: Agents Platform rollout remains opt-in. Disabled mode follows the legacy MCP path; shadow mode routes/audits without prompt/tool behavior changes; tool-policy enforcement is a separate flag.
- DEC-006: Unknown or malformed skills/tools and unavailable higher-level safety checks fail closed. No safety test is weakened to make a release gate pass.
- DEC-007: Tool authorization for side effects is not represented by a global boolean; grants are bound to request, tool and exact argument hash with expiry and confirmation state.
- DEC-008: Non-idempotent writes/execute actions are not blindly retried after ambiguous failures even when a local idempotency key exists, because local persistence cannot prove the remote side effect did not occur.
- DEC-009: The private ControlPlane pins an exact validated public commit and verifies that pin in CI before running cross-repository contract and full private regression tests.

## Known facts

- Existing root legacy state remains in `state.md`; it is not deleted or silently rewritten.
- Legacy JSON user memory remains readable/migratable; migration does not silently delete it.
- Existing owner authorization and emergency killswitch behavior remains authoritative.
- Public Agents Platform execution wraps the existing `AgentLoop`; the existing `ToolRegistry` remains the concrete handler registry.
- Memory values are injected as explicitly untrusted user-context data rather than system instructions.
- Skill workflow guidance is subordinate context and does not grant tool authorization.
- Private ControlPlane adapters expose only minimized allow/budget/side-effect decisions plus request/principal/fleet bindings needed for public enforcement.
- No release PR has been opened and neither repository's `main` branch has been modified by this work.

## Tasks

- TASK-001 DONE: inventory current public/private architecture and create `AgentsPlatform` branches.
- TASK-002 DONE: persistent Skill Registry plus validated `SKILL.md` discovery/loading and automatic hybrid Skill Router.
- TASK-003 DONE: Tool Capability Registry and Side-Effect execution policy wrapping the existing ToolRegistry.
- TASK-004 DONE: hierarchical `AGENTS.md` scope resolver.
- TASK-005 DONE: versioned Project State runtime and structured Memory v2 migration path.
- TASK-006 DONE: feature-gated Agents Platform runtime integration around the existing MCP AgentLoop, including disabled and shadow modes.
- TASK-007 DONE: private ControlPlane policy adapters, public/private boundary documentation and private regression tests.
- TASK-008 DONE: full public regression plus explicit shadow/active/enforced CI matrix.
- TASK-009 DONE: resumable DAG/workflow engine with persistence, bounded parallelism, validation, restart recovery and lease-based duplicate execution protection.
- TASK-010 DONE: routing evaluation dataset and CI gate.
- TASK-011 DONE: staged rollout/rollback documentation and feature-flag sequence.
- TASK-012 DONE FOR FUNCTIONAL CODE: second-review security findings fixed and covered by permanent regression tests.
- TASK-013 DONE FOR CROSS-REPO CODE: private policy envelope round-trips into the pinned public RuntimePolicyEnvelope and public tool enforcement; request/principal/fleet replay is rejected.
- TASK-014 IN_PROGRESS: validate this exact state-only public commit, then pin/document that exact SHA in ControlPlane and re-run private CI once more.

## Validation evidence

### Public Agents Platform — review 2

GitHub Actions run `35224503092` on public commit `892be0364ee1f1d8db0d87044a84856b91501572` completed successfully. The run reports PASS for:

- compile Agents Platform including `ToolRegistry`;
- base Agents Platform contract tests;
- review-2 security and end-to-end regressions;
- review-2 side-effect and killswitch safety tests;
- routing evaluation dataset;
- DAG workflow engine tests;
- operational health tests;
- advanced orchestration contract tests;
- integrated orchestration pipeline tests;
- tool-result and egress safety tests;
- existing skill execution regression;
- existing MCP agent hardening regression;
- existing MCP system regression;
- complete ComputeMesh regression (`python run_all_tests.py`);
- runtime matrix: shadow PASS, active PASS, enforced PASS.

The permanent review-2 tests cover active routed DAG execution, memory trust separation, runtime-policy binding, exact side-effect grants, idempotency replay, egress secret blocking, cross-process workflow leasing, scope-safe memory mutation, manifest schema/version hardening, non-idempotent write retry prevention and fail-closed killswitch behavior.

### Private ControlPlane — pinned public runtime and cross-repo enforcement

Private `ComputeMesh-ControlPlane/AgentsPlatform` GitHub Actions run `35224956044` on private commit `df452b033e1ac02d41e62f6d6ffc76ab95e8d84f` completed successfully while the `ComputeMesh` submodule was pinned to public commit `892be0364ee1f1d8db0d87044a84856b91501572`.

That run reports PASS for:

- exact public submodule SHA verification;
- public Agents Platform contract compilation;
- private adapter and cross-repo test compilation;
- Ruff;
- private Agents Platform policy tests;
- cross-repository ControlPlane -> public RuntimePolicyEnvelope -> public tool-enforcement contract;
- complete private `pytest` regression.

The cross-repository test verifies that an allowed read tool is exposed and executed, a non-allowed write tool is blocked, the existing fleet-scoped emergency-stop key receives the policy-bound fleet id, and replay across request, principal or fleet scope is rejected.

## Risks and issues

- RISK-001 MITIGATED: backward-compatibility regressions are reduced by wrapping rather than replacing the existing AgentLoop/ToolRegistry and by opt-in feature flags; legacy interrupted-workflow recovery remains tested.
- RISK-002 MITIGATED: public/private responsibility leakage is controlled by a minimized private policy envelope and explicit boundary documentation.
- RISK-003 MITIGATED: malformed/manipulated skills are validated, checksummed and fail closed; unsupported manifest schemas are recorded broken rather than auto-activated.
- RISK-004 RESOLVED: memory/skill prompt-authority mixing identified in review 1 was separated and regression-tested.
- RISK-005 RESOLVED: write confirmation/idempotency grants are exact and request-bound; non-idempotent writes are not blindly retried.
- RISK-006 RESOLVED: cross-process duplicate workflow execution is prevented by transactional node leases.
- RISK-007 RESOLVED: killswitch check errors now block execution; policy fleet binding reaches the existing fleet-scoped guard key.
- RISK-008 ACTIVE ONLY FOR RELEASE BOOKKEEPING: this state-only commit must become the final public validation candidate and then be pinned exactly by ControlPlane.

## Next actions

1. Run Agents Platform CI against this exact v4 state commit.
2. If green, pin the private ControlPlane `ComputeMesh` gitlink to that exact public SHA.
3. Create `PUBLIC_PIN.md` in ControlPlane recording the exact public SHA and validation run.
4. Re-run complete private Agents Platform CI against that final pin.
5. Review final branch diffs/status; open or merge release PRs only if explicitly requested.

## Change log

- v1: initial canonical state created from the observed repository baseline; legacy `state.md` preserved.
- v2: registry/router, tool policy, AGENTS resolver, Project State, Memory v2, feature-gated runtime, resumable DAG engine, audit/evaluation, private adapters and staged rollout implemented.
- v3: first complete public regression recorded green and project moved to exact-final-public/private-pin validation stage.
- v4: second security/architecture review findings closed in code; permanent security tests added; shadow/active/enforced public matrix and full regression green; private ControlPlane pinned to the reviewed public runtime; real cross-repository policy-to-enforcement contract and complete private regression green. This state-only revision is the final public validation candidate before exact final pin bookkeeping.
