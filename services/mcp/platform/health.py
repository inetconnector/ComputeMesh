"""Operational health/status snapshots for ComputeMesh Agents Platform."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import time
from typing import Any

from .runtime import AgentsPlatformRuntime


@dataclass(frozen=True)
class ComponentHealth:
    component: str
    status: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class AgentsPlatformHealth:
    status: str
    timestamp: float
    enabled: bool
    shadow_mode: bool
    tool_policy_enforced: bool
    components: tuple[ComponentHealth, ...]
    initialization_errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["components"] = [asdict(component) for component in self.components]
        return value


def _path_status(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {"configured": False}
    candidate = Path(path)
    return {
        "configured": True,
        "exists": candidate.exists(),
        "path": str(candidate),
        "size_bytes": candidate.stat().st_size if candidate.exists() and candidate.is_file() else None,
    }


def collect_agents_platform_health(runtime: AgentsPlatformRuntime) -> AgentsPlatformHealth:
    """Return a non-secret operational snapshot suitable for diagnostics/admin UI."""
    components: list[ComponentHealth] = []
    enabled = bool(runtime.config.agents_platform_enabled)
    if not enabled:
        return AgentsPlatformHealth(
            status="DISABLED",
            timestamp=time.time(),
            enabled=False,
            shadow_mode=False,
            tool_policy_enforced=False,
            components=(),
            initialization_errors=(),
        )

    registry_detail: dict[str, Any] = {}
    if runtime.skill_registry is not None:
        try:
            registry_detail = runtime.skill_registry.health()
            integrity = registry_detail.get("integrity")
            registry_status = "HEALTHY" if integrity == "ok" else "DEGRADED"
        except Exception as exc:
            registry_status = "DEGRADED"
            registry_detail = {"error": str(exc)}
    else:
        registry_status = "UNAVAILABLE"
    components.append(ComponentHealth("skill_registry", registry_status, registry_detail))

    components.append(ComponentHealth(
        "skill_router",
        "HEALTHY" if runtime.router is not None else "UNAVAILABLE",
        {
            "minimum_score": runtime.config.agents_platform_routing_min_score,
            "ambiguity_margin": runtime.config.agents_platform_routing_ambiguity_margin,
        },
    ))
    components.append(ComponentHealth(
        "tool_policy",
        "HEALTHY" if runtime.safe_tool_executor is not None else "UNAVAILABLE",
        {"enforced": bool(runtime.config.agents_platform_enforce_tool_policy)},
    ))
    components.append(ComponentHealth(
        "agents_rules",
        "HEALTHY" if runtime.rule_resolver is not None else "UNAVAILABLE",
        {"repo_root": str(runtime.repo_root)},
    ))
    memory_path = getattr(runtime.memory, "db_path", None) if runtime.memory is not None else None
    components.append(ComponentHealth(
        "memory",
        "HEALTHY" if runtime.memory is not None else "UNAVAILABLE",
        _path_status(memory_path),
    ))
    project_state_path = getattr(runtime.project_state, "state_path", None) if runtime.project_state is not None else None
    components.append(ComponentHealth(
        "project_state",
        "HEALTHY" if runtime.project_state is not None else "UNAVAILABLE",
        _path_status(project_state_path),
    ))
    audit_path = getattr(runtime.audit, "path", None) if runtime.audit is not None else None
    components.append(ComponentHealth(
        "audit",
        "HEALTHY" if runtime.audit is not None else "UNAVAILABLE",
        _path_status(audit_path),
    ))

    errors = tuple(runtime.initialization_errors)
    component_states = {component.status for component in components}
    if errors or "UNAVAILABLE" in component_states or "DEGRADED" in component_states:
        status = "DEGRADED"
    elif runtime.config.agents_platform_shadow_mode:
        status = "SHADOW"
    else:
        status = "HEALTHY"
    return AgentsPlatformHealth(
        status=status,
        timestamp=time.time(),
        enabled=True,
        shadow_mode=bool(runtime.config.agents_platform_shadow_mode),
        tool_policy_enforced=bool(runtime.config.agents_platform_enforce_tool_policy),
        components=tuple(components),
        initialization_errors=errors,
    )
