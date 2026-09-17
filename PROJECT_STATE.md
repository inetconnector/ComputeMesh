---
document_type: PROJECT_STATE
state_schema_version: "1.0"
project_state_version: 3
project_id: "PRJ-20260917-AGENTS-PLATFORM"
project_name: "ComputeMesh Agents Platform"
status: VALIDATING_PRIVATE_PIN
created_at: "2026-09-17T11:47:00+02:00"
updated_at: "2026-09-17T14:02:00+02:00"
state_owner: "ComputeMesh"
primary_goal: "Introduce a production-oriented agent platform without replacing existing MCP, memory, security or control-plane subsystems."
integrity_status: PUBLIC_VALIDATED
---

# Executive state snapshot

The public ComputeMesh `AgentsPlatform` branch contains the generic agent-runtime layer required by the implementation plan: persistent skill registry, automatic hybrid skill router, capability/side-effect tool policy, hierarchical `AGENTS.md` resolution, resumable DAG/workflow execution, versioned project state, structured scoped memory, audit/observability hooks, feature-gated integration around the existing MCP `AgentLoop`, routing evaluation and staged rollback documentation.

The private `ComputeMesh-ControlPlane/AgentsPlatform` branch contains only private policy/rollout adapters and preserves the public/private responsibility boundary. Existing MCP execution, owner authorization and emergency killswitch behavior remain authoritative.

The former public release blocker caused by third-party Google Fonts in `portal/ai-auth.html` has been removed without weakening the Portal security test. Public Agents Platform CI run `35218556118` on commit `cdc61dd4fbd990cb24ac832ba78d7a059710fe0c` passed all component gates and the complete ComputeMesh regression. This state/documentation revision must itself be validated before becoming the exact public pin for the private ControlPlane.

## Scope

Public ComputeMesh owns generic runtime contracts and reusable implementations for request envelopes, skill registry/routing, DAG/workflow execution, tool capability/side-effect policy, AGENTS scope resolution, project state, structured memory, validation/provenance, audit and feature-gated integration.

Private ControlPlane owns fleet/model/commercial/billing/provider/placement policy and production-specific authorization/rollout decisions. Private scoring inputs, economics, credentials and fleet internals are not copied into the public runtime.

## Requirements

- REQ-001 DONE: persistent, versioned, validated skill registry with checksums and lifecycle state.
- REQ-002 DONE: request envelope plus hybrid skill routing with abstention, ambiguity handling, dependencies/conflicts, context budget and DAG output.
- REQ-003 DONE: capability/side-effect policy in front of the existing ToolRegistry with preview/confirm/execute/verify, authorization, idempotency, retry and circuit breaking.
- REQ-004 DONE: hierarchical AGENTS rule discovery and root-to-leaf scope resolution.
- REQ-005 DONE: canonical, versioned, atomic project-state persistence with checkpoints and stale-write detection.
- REQ-006 DONE: scoped/provenance-aware structured memory with expiry, conflict/supersession behavior, deletion and legacy JSON migration.
- REQ-007 DONE: feature-gated runtime facade and documented staged rollout/rollback path.
- REQ-008 DONE FOR PUBLIC CODE: component/security/MCP/full public regression gates pass after the Portal blocker was fixed; exact final state/documentation commit is being revalidated before private pinning.
- REQ-009 DONE: persistent resumable DAG/workflow engine with bounded parallelism, retry, validation, resume and duplicate-definition/execution protection.
- REQ-010 DONE: routing evaluation dataset and append-only observable decision audit.

## Decisions

- DEC-001: Extend `services/mcp` instead of introducing a parallel agent loop.
- DEC-002: Keep the existing MCP `ToolRegistry` as the concrete execution backend and place capability/side-effect policy in front of it.
- DEC-003: Use SQLite for durable skill, memory, workflow and execution-policy state; use atomic versioned project-state snapshots/checkpoints for resumability.
- DEC-004: Keep private fleet/model/billing/provider/placement policy out of public generic runtime code.
- DEC-005: Agents Platform rollout remains opt-in. Disabled mode follows the legacy MCP path; shadow mode routes/audits without prompt/tool behavior changes; tool-policy enforcement is a separate flag.
- DEC-006: Unknown or malformed skills/tools fail closed. No safety test is weakened to make a release gate pass.
- DEC-007: The Portal third-party-font violation was resolved by removing external browser font resources, not by weakening the Portal security test.
- DEC-008: The private ControlPlane must pin the exact final validated public commit and re-run its complete validation layer before release readiness can be declared.

## Known facts

- Existing root legacy state remains in `state.md`; it is not deleted or silently rewritten.
- Legacy JSON user memory remains readable/migratable; migration does not silently delete it.
- Existing owner authorization and emergency killswitch behavior remains authoritative.
- Public Agents Platform execution is wrapped around the existing `AgentLoop`; the existing `ToolRegistry` remains the concrete handler registry.
- Private ControlPlane adapters expose only minimized allow/deny/budget/side-effect decisions to the public runtime.
- `portal/ai-auth.html` no longer contains `fonts.googleapis.com` or `fonts.gstatic.com` references on the AgentsPlatform branch.

## Tasks

- TASK-001 DONE: inventory current public/private architecture and create `AgentsPlatform` branches.
- TASK-002 DONE: persistent Skill Registry plus validated `SKILL.md` discovery/loading and automatic hybrid Skill Router.
- TASK-003 DONE: Tool Capability Registry and Side-Effect execution policy wrapping the existing ToolRegistry.
- TASK-004 DONE: hierarchical `AGENTS.md` scope resolver.
- TASK-005 DONE: versioned Project State runtime and structured Memory v2 migration path.
- TASK-006 DONE: feature-gated Agents Platform runtime integration around the existing MCP AgentLoop, including disabled and shadow modes.
- TASK-007 DONE: private ControlPlane policy adapters, public/private boundary documentation and private regression tests.
- TASK-008 DONE FOR PUBLIC CODE: the public full regression passed after removal of forbidden Portal font origins; exact final documentation/state commit is now the validation candidate.
- TASK-009 DONE: resumable DAG/workflow engine with persistence, bounded parallelism, retries, node validation, restart recovery and duplicate execution/definition safeguards.
- TASK-010 DONE: routing evaluation dataset and CI gate.
- TASK-011 DONE: staged rollout/rollback documentation and feature-flag sequence.
- TASK-012 IN_PROGRESS: validate this exact final public candidate, update the private ControlPlane gitlink/public-pin marker, and re-run complete private CI.

## Validation evidence

### Public Agents Platform and full regression

GitHub Actions run `35218556118` on public commit `cdc61dd4fbd990cb24ac832ba78d7a059710fe0c` completed successfully. The run reports PASS for:

- compile Agents Platform;
- Agents Platform contract tests;
- routing evaluation dataset;
- DAG workflow engine tests;
- operational health tests;
- advanced orchestration contract tests;
- integrated orchestration pipeline tests;
- tool-result and egress safety tests;
- existing skill execution regression;
- existing MCP agent hardening regression;
- existing MCP system regression;
- full ComputeMesh regression (`python run_all_tests.py`).

The preceding complete public run had executed 775 tests with exactly one Portal security-policy failure. The external Google Fonts references causing that failure were subsequently removed from `portal/ai-auth.html`, and the full gate then passed.

### Private ControlPlane validation

Private `ComputeMesh-ControlPlane/AgentsPlatform` GitHub Actions run `35212852178` on private commit `7f70ab0d46fccad80c92e25c697cb4df92f4ea0c` passed:

- public submodule contract verification;
- private adapter compile;
- Ruff;
- private Agents Platform policy tests;
- complete private `pytest` regression.

That run validated an older public pin (`dc77b25a59190c53ccc19578374acd71128df028`). The private branch must therefore be advanced to the exact final validated public candidate produced after this state update and then re-tested.

## Risks and issues

- RISK-001 MITIGATED: backward-compatibility regressions are reduced by wrapping rather than replacing the existing AgentLoop/ToolRegistry and by opt-in feature flags.
- RISK-002 MITIGATED: public/private responsibility leakage is controlled by a minimized private policy envelope and explicit boundary documentation.
- RISK-003 MITIGATED: malformed/manipulated skills are validated, checksummed and fail closed; broken skills are not auto-activated.
- RISK-004 RESOLVED: forbidden third-party Portal font resources were removed and the full public gate passed.
- RISK-005 ACTIVE: private ControlPlane submodule pin must be updated to the exact final validated public commit and revalidated.

## Next actions

1. Run Agents Platform CI against this exact state/documentation candidate commit.
2. If green, update the private ControlPlane `ComputeMesh` gitlink and `PUBLIC_PIN.md` to that exact public SHA.
3. Re-run the complete private Agents Platform CI against the updated pin.
4. Record the exact public/private validation pair and review the final public/private diff.
5. Open or merge release PRs only if explicitly requested.

## Change log

- v1: initial canonical state created from the observed repository baseline; legacy `state.md` preserved.
- v2: registry/router, tool policy, AGENTS resolver, Project State, Memory v2, feature-gated runtime, resumable DAG engine, audit/evaluation, private adapters and staged rollout implemented; exact CI evidence recorded; pre-existing Portal full-suite blocker retained explicitly.
- v3: Portal third-party font blocker resolved without weakening security policy; full public regression recorded green; project moved to exact-final-public-candidate/private-pin validation stage.
