# SPDX-License-Identifier: Apache-2.0
"""Configuration and security policy for ComputeMesh MCP Subsystem."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false")
    return raw.lower() in ("1", "true", "yes", "on")


@dataclass
class MCPConfig:
    enabled: bool = True
    web_search_enabled: bool = True
    finance_enabled: bool = True
    web_fetch_enabled: bool = True
    system_tools_enabled: bool = False  # Disabled by default, only enabled for explicit owner local tools
    config_path: str = ""
    max_agent_iterations: int = 5
    request_timeout_seconds: float = 15.0
    allowed_domains: List[str] = field(default_factory=lambda: ["*"])
    custom_mcp_servers: dict = field(default_factory=dict)

    # Agents Platform rollout controls. Active by default with backward-compatible fallback.
    agents_platform_enabled: bool = True
    agents_platform_shadow_mode: bool = False
    agents_platform_enforce_tool_policy: bool = False
    agents_platform_skill_roots: str = "skills;services/mcp"
    agents_platform_registry_db: str = "data/agents/skill_registry.sqlite3"
    agents_platform_memory_db: str = "data/agents/memory.sqlite3"
    agents_platform_audit_log: str = "data/agents/audit.jsonl"
    agents_platform_project_state: str = "data/agents/project_state.json"
    agents_platform_routing_min_score: float = 0.28
    agents_platform_routing_ambiguity_margin: float = 0.08

    @classmethod
    def from_env(cls) -> "MCPConfig":
        try:
            max_iter = int(os.getenv("COMPUTEMESH_MCP_MAX_ITERATIONS", "5"))
        except ValueError:
            max_iter = 5
        try:
            timeout_s = float(os.getenv("COMPUTEMESH_MCP_TIMEOUT_SECONDS", "15.0"))
        except ValueError:
            timeout_s = 15.0
        try:
            route_min = float(os.getenv("COMPUTEMESH_AGENTS_ROUTING_MIN_SCORE", "0.28"))
        except ValueError:
            route_min = 0.28
        try:
            ambiguity_margin = float(os.getenv("COMPUTEMESH_AGENTS_ROUTING_AMBIGUITY_MARGIN", "0.08"))
        except ValueError:
            ambiguity_margin = 0.08

        return cls(
            enabled=_env_bool("COMPUTEMESH_MCP_ENABLED", True),
            web_search_enabled=_env_bool("COMPUTEMESH_MCP_WEB_SEARCH_ENABLED", True),
            finance_enabled=_env_bool("COMPUTEMESH_MCP_FINANCE_ENABLED", True),
            web_fetch_enabled=_env_bool("COMPUTEMESH_MCP_WEB_FETCH_ENABLED", True),
            system_tools_enabled=_env_bool("COMPUTEMESH_MCP_SYSTEM_TOOLS_ENABLED", False),
            config_path=os.getenv("COMPUTEMESH_MCP_CONFIG_PATH", ""),
            max_agent_iterations=max_iter,
            request_timeout_seconds=timeout_s,
            agents_platform_enabled=_env_bool("COMPUTEMESH_AGENTS_PLATFORM_ENABLED", True),
            agents_platform_shadow_mode=_env_bool("COMPUTEMESH_AGENTS_PLATFORM_SHADOW_MODE", False),
            agents_platform_enforce_tool_policy=_env_bool("COMPUTEMESH_AGENTS_ENFORCE_TOOL_POLICY", False),
            agents_platform_skill_roots=os.getenv("COMPUTEMESH_AGENTS_SKILL_ROOTS", "skills;services/mcp"),
            agents_platform_registry_db=os.getenv("COMPUTEMESH_AGENTS_REGISTRY_DB", "data/agents/skill_registry.sqlite3"),
            agents_platform_memory_db=os.getenv("COMPUTEMESH_AGENTS_MEMORY_DB", "data/agents/memory.sqlite3"),
            agents_platform_audit_log=os.getenv("COMPUTEMESH_AGENTS_AUDIT_LOG", "data/agents/audit.jsonl"),
            agents_platform_project_state=os.getenv("COMPUTEMESH_AGENTS_PROJECT_STATE", "data/agents/project_state.json"),
            agents_platform_routing_min_score=route_min,
            agents_platform_routing_ambiguity_margin=ambiguity_margin,
        )


_default_config: Optional[MCPConfig] = None


def get_mcp_config() -> MCPConfig:
    global _default_config
    if _default_config is None:
        _default_config = MCPConfig.from_env()
    return _default_config


def set_mcp_config(cfg: MCPConfig) -> None:
    global _default_config
    _default_config = cfg
