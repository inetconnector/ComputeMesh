---
document_type: PROJECT_STATE
state_schema_version: "1.0"
project_state_version: 2
project_id: "PRJ-20260917-AGENTS-PLATFORM"
project_name: "ComputeMesh Agents Platform"
status: ACTIVE
created_at: "2026-09-17T11:47:00+02:00"
updated_at: "2026-09-17T13:03:00+02:00"
state_owner: "ComputeMesh"
primary_goal: "Introduce a production-oriented agent platform without replacing existing MCP, memory, security or control-plane subsystems."
integrity_status: PARTIALLY_VALIDATED
---

# Executive state snapshot

The public ComputeMesh `AgentsPlatform` branch now contains the generic agent-runtime layer required by the implementation plan: persistent skill registry, automatic hybrid skill router, capability/side-effect tool policy, hierarchical `AGENTS.md` resolution, resumable DAG/workflow execution, versioned project state, structured scoped memory, audit/observability hooks, feature-gated integration around the existing MCP `AgentLoop`, routing evaluation and staged rollback documentation.

The private `ComputeMesh-ControlPlane/AgentsPlatform` branch contains only private policy/rollout adapters and preserves the public/private responsibility boundary. Existing MCP execution, owner authorization and emergency killswitch behavior remain authoritative.

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
- REQ-008 PARTIAL: component/security/private regression gates pass; full public regression has one pre-existing Portal security-policy failure unrelated to Agents Platform.
- REQ-009 DONE: persistent resumable DAG/workflow engine with bounded parallelism, retry, validation, resume and duplicate-definition/execution protection.
- REQ-010 DONE: routing evaluation dataset and append-only observable decision audit.

## Decisions

- DEC-001: Extend `services/mcp` instead of introducing a parallel agent loop.
- DEC-002: Keep the existing MCP `ToolRegistry` as the concrete execution backend and place capability/side-effect policy in front of it.
- DEC-003: Use SQLite for durable skill, memory, workflow and execution-policy state; use atomic versioned project-state snapshots/checkpoints for resumability.
- DEC-004: Keep private fleet/model/billing/provider/placement policy out of public generic runtime code.
- DEC-005: Agents Platform rollout remains opt-in. Disabled mode follows the legacy MCP path; shadow mode routes/audits without prompt/tool behavior changes; tool-policy enforcement is a separate flag.
- DEC-006: Unknown or malformed skills/tools fail closed. No safety test is weakened to make a release gate pass.
- DEC-007: The existing Portal third-party-font violation is tracked as a separate baseline release blocker rather than being attributed to Agents Platform.

## Known facts

- Existing root legacy state remains in `state.md`; it is not deleted or silently rewritten.
- Legacy JSON user memory remains readable/migratable; migration does not silently delete it.
- Existing owner authorization and emergency killswitch behavior remains authoritative.
- Public Agents Platform execution is wrapped around the existing `AgentLoop`; the existing `ToolRegistry` remains the concrete handler registry.
- Private ControlPlane adapters expose only minimized allow/deny/budget/side-effect decisions to the public runtime.

## Tasks

- TASK-001 DONE: inventory current public/private architecture and create `AgentsPlatform` branches.
- TASK-002 DONE: persistent Skill Registry plus validated `SKILL.md` discovery/loading and automatic hybrid Skill Router.
- TASK-003 DONE: Tool Capability Registry and Side-Effect execution policy wrapping the existing ToolRegistry.
- TASK-004 DONE: hierarchical `AGENTS.md` scope resolver.
- TASK-005 DONE: versioned Project State runtime and structured Memory v2 migration path.
- TASK-006 DONE: feature-gated Agents Platform runtime integration around the existing MCP AgentLoop, including disabled and shadow modes.
- TASK-007 DONE: private ControlPlane policy adapters, public/private boundary documentation and private regression tests.
- TASK-008 IN_PROGRESS: release validation. Agents Platform-specific and MCP regressions pass; full public suite is 774/775 because of a pre-existing Portal Google Fonts violation.
- TASK-009 DONE: resumable DAG/workflow engine with persistence, bounded parallelism, retries, node validation, restart recovery and duplicate execution/definition safeguards.
- TASK-010 DONE: routing evaluation dataset and CI gate.
- TASK-011 DONE: staged rollout/rollback documentation and feature-flag sequence.
- TASK-012 BLOCKED: final release pin/merge readiness pending resolution or explicit disposition of the pre-existing Portal security-policy failure and re-validation of the exact final public commit in the private submodule.

## Validation evidence

### Public Agents Platform component gates

On public commit `940781fa198de61efc1d8ef28b0e901847668bb5`, GitHub Actions run `35213444586` reports:

- compile Agents Platform: PASS;
- Agents Platform contract tests: PASS (14 tests);
- routing evaluation dataset: PASS;
- DAG workflow engine tests: PASS (9 tests after the explicit retry-reset defect was fixed);
- existing skill execution regression: PASS;
- existing MCP agent hardening regression: PASS;
- existing MCP system regression: PASS.

### Full public ComputeMesh regression

The full `python run_all_tests.py` gate is not yet green. A prior complete run executed 775 tests with 774 passing and one failure in `services.portal.tests.test_portal_server.TestPortalServer.test_portal_html_has_no_forbidden_third_party_resources` because `portal/ai-auth.html` references `fonts.googleapis.com` and `fonts.gstatic.com`.

This violation is present on `main` as well as `AgentsPlatform`; it is therefore a baseline Portal/security-policy issue, not an Agents Platform regression. The safety test remains unchanged.

### Private ControlPlane validation

Private `ComputeMesh-ControlPlane/AgentsPlatform` GitHub Actions run `35212852178` on private commit `7f70ab0d46fccad80c92e25c697cb4df92f4ea0c` passed:

- public submodule contract verification;
- private adapter compile;
- Ruff;
- private Agents Platform policy tests;
- complete private `pytest` regression.

The private branch currently pins public commit `dc77b25a59190c53ccc19578374acd71128df028`. It must be advanced to the final validated public release candidate and re-tested before merge/release.

## Risks and issues

- RISK-001 MITIGATED: backward-compatibility regressions are reduced by wrapping rather than replacing the existing AgentLoop/ToolRegistry and by opt-in feature flags.
- RISK-002 MITIGATED: public/private responsibility leakage is controlled by a minimized private policy envelope and explicit boundary documentation.
- RISK-003 MITIGATED: malformed/manipulated skills are validated, checksummed and fail closed; broken skills are not auto-activated.
- RISK-004 ACTIVE: public full-suite release gate remains red because of the pre-existing Portal third-party font references.
- RISK-005 ACTIVE: private ControlPlane submodule pin must be updated only after the exact final public candidate is chosen.

## Next actions

1. Resolve or formally disposition the pre-existing Portal third-party-font security-policy failure without weakening the test.
2. Re-run the full public `run_all_tests.py` gate on the exact final public commit.
3. Update the private ControlPlane `ComputeMesh` gitlink to that exact public commit.
4. Re-run the complete private Agents Platform CI against the updated pin.
5. Review branch diffs and public/private boundary; only then open/merge release PRs if explicitly requested.

## Change log

- v1: initial canonical state created from the observed repository baseline; legacy `state.md` preserved.
- v2: registry/router, tool policy, AGENTS resolver, Project State, Memory v2, feature-gated runtime, resumable DAG engine, audit/evaluation, private adapters and staged rollout implemented; exact CI evidence recorded; pre-existing Portal full-suite blocker retained explicitly.
