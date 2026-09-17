---
document_type: PROJECT_STATE
state_schema_version: "1.0"
project_state_version: 1
project_id: "PRJ-20260917-AGENTS-PLATFORM"
project_name: "ComputeMesh Agents Platform"
status: ACTIVE
created_at: "2026-09-17T11:47:00+02:00"
updated_at: "2026-09-17T11:47:00+02:00"
state_owner: "ComputeMesh"
primary_goal: "Introduce a production-oriented agent platform without replacing existing MCP, memory, security or control-plane subsystems."
integrity_status: UNVERIFIED
---

# Executive state snapshot

ComputeMesh already contains an MCP `AgentLoop`, central `ToolRegistry`, universal `SKILL.md`/skill executor, a persistent JSON user-memory component and legacy `state.md`. The Agents Platform migration extends these components instead of duplicating them.

## Scope

Public ComputeMesh: generic runtime contracts and implementations for skill registry/routing, tool policy, AGENTS scope resolution, structured project state, structured memory, validation/provenance and observability hooks.

Private ControlPlane: fleet/model/commercial/billing policy and production orchestration adapters.

## Requirements

- REQ-001: persistent, versioned, validated skill registry with checksums and lifecycle state.
- REQ-002: request envelope plus hybrid skill routing with abstention, ambiguity handling, dependencies/conflicts and DAG output.
- REQ-003: capability/side-effect policy in front of the existing ToolRegistry.
- REQ-004: hierarchical AGENTS rule discovery and scope resolution.
- REQ-005: canonical, versioned, atomic project-state persistence with checkpoints and stale-write detection.
- REQ-006: scoped/provenance-aware memory with migration from the legacy JSON store.
- REQ-007: feature-gated integration and rollback path.
- REQ-008: regression/security tests and explicit validation evidence.

## Decisions

- DEC-001: Extend `services/mcp` instead of introducing a parallel agent loop.
- DEC-002: Keep the existing MCP `ToolRegistry` as the execution backend.
- DEC-003: Use SQLite for durable registry/memory metadata and atomic JSON/Markdown sidecars for project state.
- DEC-004: Keep private fleet/model/billing policy out of public generic runtime code.

## Known facts

- Existing root legacy state remains in `state.md`; it is not deleted or silently rewritten.
- Existing owner authorization and emergency killswitch behavior remains authoritative.

## Tasks

- TASK-001 DONE: inventory current public/private architecture and create `AgentsPlatform` branches.
- TASK-002 IN_PROGRESS: implement persistent skill registry and router contracts.
- TASK-003 PLANNED: tool capability and side-effect execution policy.
- TASK-004 PLANNED: AGENTS scope resolver.
- TASK-005 PLANNED: project-state runtime and memory v2 migration.
- TASK-006 PLANNED: integrate with MCP agent loop through feature-gated runtime facade.
- TASK-007 PLANNED: private ControlPlane adapters and policy boundary tests.
- TASK-008 PLANNED: run regression/security validation and record results.

## Risks

- RISK-001: backward-compatibility regressions if existing tool execution is replaced rather than wrapped.
- RISK-002: accidental public/private responsibility leakage.
- RISK-003: unsafe activation of malformed or manipulated skills.

## Next actions

Implement TASK-002 through TASK-007 in phase-oriented commits; then validate and update this state with actual test evidence.

## Change log

- v1: initial canonical state created from the observed repository baseline; legacy `state.md` preserved.
