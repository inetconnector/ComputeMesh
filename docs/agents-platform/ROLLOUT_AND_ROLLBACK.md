# Agents Platform Rollout and Rollback

## Feature flags

The Agents Platform is opt-in and backwards-compatible by default:

- `COMPUTEMESH_AGENTS_PLATFORM_ENABLED=false`: legacy MCP/AgentLoop path only.
- `COMPUTEMESH_AGENTS_PLATFORM_ENABLED=true` and `COMPUTEMESH_AGENTS_PLATFORM_SHADOW_MODE=true`: build registry, route and audit, but do not inject platform context or enforce tool policy.
- `COMPUTEMESH_AGENTS_PLATFORM_SHADOW_MODE=false`: selected validated skill/rule/memory context may be injected.
- `COMPUTEMESH_AGENTS_ENFORCE_TOOL_POLICY=true`: additionally route AgentLoop tool calls through the capability/side-effect policy facade.

Tool-policy enforcement must not be enabled before the platform itself is enabled and its shadow-mode evaluation is acceptable.

## Staged rollout

1. **Disabled baseline** — deploy code with all Agents Platform flags off. Verify legacy MCP behavior.
2. **Shadow routing** — enable the platform in shadow mode. Compare routing/audit decisions against the evaluation dataset and production observations without changing model context or tool execution.
3. **Context integration** — disable shadow mode for a limited fleet/environment while keeping tool-policy enforcement off. Validate selected skill, AGENTS and scoped-memory context.
4. **Read-only policy enforcement** — enable tool policy where manifests are classified and expected actions are read-only.
5. **Side-effect enforcement** — allow write/execute classes only with explicit authorization, confirmation and idempotency requirements.
6. **Broader rollout** — expand only after public regression, private ControlPlane regression and operational monitoring remain green.

## Rollback

Rollback does not require deleting migrated data.

1. Set `COMPUTEMESH_AGENTS_ENFORCE_TOOL_POLICY=false`.
2. Set `COMPUTEMESH_AGENTS_PLATFORM_SHADOW_MODE=true` if routing/audit observation should continue, or set `COMPUTEMESH_AGENTS_PLATFORM_ENABLED=false` for the complete legacy path.
3. Keep skill-registry, memory, project-state and audit databases for diagnosis and future resume.
4. Never delete or rewrite legacy `state.md` or legacy user-memory JSON as part of rollback.
5. If a private ControlPlane pin is involved, revert its ComputeMesh submodule to the previous validated public commit.
6. Re-run public and private regression gates after the rollback pin/configuration change.

## Release evidence

A release candidate must record the exact public commit, private pin (when applicable), Agents Platform CI result, routing-evaluation result and full regression result. A command not actually executed is recorded as unverified, never as passing.
