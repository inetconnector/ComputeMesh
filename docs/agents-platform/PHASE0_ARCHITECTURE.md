# Agents Platform Phase 0 — Architecture Baseline

## Observed public baseline

- `services/mcp/agent_loop.py`: bounded multi-turn autonomous MCP tool loop with direct-intent preflight and batched execution.
- `services/mcp/tool_registry.py`: central built-in/custom tool registry, owner-only authorization, schema checks, emergency killswitch check, TTL cache and batch execution.
- `services/mcp/skill_execution.py` + `services/mcp/SKILL.md`: in-memory skill registry and universal skill workflow.
- `services/memory/user_memory.py`: persistent JSON key/value user memory and profile summary injection.
- `state.md`: legacy project/repository state document.
- `.agents/rules/`: existing repository-local rule material, but no hierarchical `AGENTS.md` resolver.

## Observed private ControlPlane baseline

The private repository contains dedicated `services/` for fleet, dispatch, placement, performance, pricing, compliance and related production concerns, plus private tests and `.agents/rules`. It also pins ComputeMesh as a submodule.

## Target boundary

### Public ComputeMesh owns

Generic request, skill, tool-policy, state, memory, rule-resolution, audit and validation contracts that can operate independently of a specific fleet/business deployment.

### Private ControlPlane owns

Fleet identity and policy, model/commercial policy, production scheduling/placement policy, billing/settlement, provider administration and private orchestration integrations.

## Migration strategy

1. Add new contracts and persistent stores without deleting legacy APIs.
2. Load existing `SKILL.md` documents into a validated SQLite registry; malformed skills remain `BROKEN`/inactive.
3. Wrap existing `ToolRegistry`; do not fork its handlers.
4. Add feature-gated Agent Platform integration so rollout can be disabled without reverting data formats.
5. Migrate legacy user-memory JSON by explicit import while retaining read compatibility.
6. Preserve `state.md`; canonical Agents Platform state lives in `PROJECT_STATE.md` plus machine-readable runtime snapshots/checkpoints.
7. Point the private ControlPlane submodule/adapters at the public AgentsPlatform commit after public validation.

## Baseline validation commands

Public repository expected gates:

```bash
python -m compileall -q apps deploy models protocol runtime sdk services setup tests tools
python -m unittest services.mcp.tests.test_skill_execution -v
python run_all_tests.py
```

Private ControlPlane expected gates:

```bash
python -m compileall -q services tests
pytest -q
ruff check services tests
```

Results must be recorded as observed; a command that was not executed is not considered passing.
