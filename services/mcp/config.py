# SPDX-License-Identifier: Apache-2.0
"""
Configuration and security policy for ComputeMesh MCP Subsystem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional


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

    @classmethod
    def from_env(cls) -> "MCPConfig":
        enabled_env = os.getenv("COMPUTEMESH_MCP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        web_search_env = os.getenv("COMPUTEMESH_MCP_WEB_SEARCH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        finance_env = os.getenv("COMPUTEMESH_MCP_FINANCE_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        web_fetch_env = os.getenv("COMPUTEMESH_MCP_WEB_FETCH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
        system_tools_env = os.getenv("COMPUTEMESH_MCP_SYSTEM_TOOLS_ENABLED", "false").lower() in ("1", "true", "yes", "on")
        config_path_env = os.getenv("COMPUTEMESH_MCP_CONFIG_PATH", "")

        try:
            max_iter = int(os.getenv("COMPUTEMESH_MCP_MAX_ITERATIONS", "5"))
        except ValueError:
            max_iter = 5

        try:
            timeout_s = float(os.getenv("COMPUTEMESH_MCP_TIMEOUT_SECONDS", "15.0"))
        except ValueError:
            timeout_s = 15.0

        return cls(
            enabled=enabled_env,
            web_search_enabled=web_search_env,
            finance_enabled=finance_env,
            web_fetch_enabled=web_fetch_env,
            system_tools_enabled=system_tools_env,
            config_path=config_path_env,
            max_agent_iterations=max_iter,
            request_timeout_seconds=timeout_s,
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
