# SPDX-License-Identifier: Apache-2.0
"""
ComputeMesh MCP (Model Context Protocol) & Live Tool Engine.

Legacy MCP exports remain stable. The Agents Platform runtime is an opt-in,
feature-gated integration layer over the existing AgentLoop and ToolRegistry.
"""

from .config import MCPConfig, get_mcp_config
from .tool_registry import ToolRegistry, ToolDefinition
from .mcp_client import MCPClient, MCPStdioClient
from .agent_loop import AgentLoop, AgentExecutionResult
from .skill_execution import SkillExecutionEngine, SkillRegistry, SkillSpec
from .platform import AgentsPlatformRuntime, build_agents_platform_runtime

__all__ = [
    "MCPConfig",
    "get_mcp_config",
    "ToolRegistry",
    "ToolDefinition",
    "MCPClient",
    "MCPStdioClient",
    "AgentLoop",
    "AgentExecutionResult",
    "SkillExecutionEngine",
    "SkillRegistry",
    "SkillSpec",
    "AgentsPlatformRuntime",
    "build_agents_platform_runtime",
]
