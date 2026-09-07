# SPDX-License-Identifier: Apache-2.0
"""
ComputeMesh MCP (Model Context Protocol) & Live Tool Engine
Enables real-time data retrieval (Web Search, Financial Market Quotes, URL Reader)
and official Model Context Protocol (MCP) server integration for authenticated fleet owners.
"""

from .config import MCPConfig, get_mcp_config
from .tool_registry import ToolRegistry, ToolDefinition
from .mcp_client import MCPClient, MCPStdioClient
from .agent_loop import AgentLoop, AgentExecutionResult

__all__ = [
    "MCPConfig",
    "get_mcp_config",
    "ToolRegistry",
    "ToolDefinition",
    "MCPClient",
    "MCPStdioClient",
    "AgentLoop",
    "AgentExecutionResult",
]
