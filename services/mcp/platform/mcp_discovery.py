# SPDX-License-Identifier: Apache-2.0
"""Bounded, origin-aware discovery for external MCP tools.

The legacy :class:`MCPClient` can still register every configured server into
``ToolRegistry``.  Agents need a narrower surface: discovery metadata may be
searched without putting every schema in the model context, and execution
must be explicitly enabled for an exact qualified tool id.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .tool_contracts import SecretScanner


class MCPDiscoveryError(RuntimeError):
    """Raised for invalid broker input or an unavailable discovery record."""


class MCPOrigin(str, Enum):
    STDIO = "stdio"
    HTTP = "http"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MCPDiscoveryPolicy:
    """Minimized policy for one discovery view or tool invocation."""

    allowed_origins: frozenset[str] = frozenset({MCPOrigin.STDIO.value, MCPOrigin.HTTP.value})
    allowed_servers: frozenset[str] | None = None
    allowed_tools: frozenset[str] | None = None
    allow_execution: bool = False

    def allows(self, tool: "MCPToolDescriptor", *, execute: bool = False) -> bool:
        if tool.origin.value not in self.allowed_origins:
            return False
        if self.allowed_servers is not None and tool.server_name not in self.allowed_servers:
            return False
        if self.allowed_tools is not None and tool.qualified_name not in self.allowed_tools:
            return False
        return not execute or self.allow_execution


@dataclass(frozen=True)
class MCPToolDescriptor:
    server_name: str
    tool_name: str
    qualified_name: str
    description: str
    origin: MCPOrigin
    schema_checksum: str
    input_schema: Mapping[str, Any] = field(repr=False)

    def summary(self) -> dict[str, Any]:
        """Return the schema-free representation intended for model search."""
        return {
            "tool_id": self.qualified_name,
            "server": self.server_name,
            "name": self.tool_name,
            "description": self.description,
            "origin": self.origin.value,
            "schema_checksum": self.schema_checksum,
        }

    def detail(self) -> dict[str, Any]:
        value = self.summary()
        value["input_schema"] = _bounded_json_value(self.input_schema)
        return value


@dataclass(frozen=True)
class MCPServerStatus:
    server_name: str
    origin: MCPOrigin
    ready: bool
    tool_count: int
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.server_name,
            "origin": self.origin.value,
            "ready": self.ready,
            "tool_count": self.tool_count,
            **({"error_code": self.error_code} if self.error_code else {}),
        }


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_DESCRIPTION = 4_000
_MAX_SCHEMA_BYTES = 128 * 1024


def _bounded_json_value(value: Any) -> Any:
    """Copy JSON-compatible schema data and cap nested collection size."""
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > _MAX_SCHEMA_BYTES:
        raise MCPDiscoveryError("MCP tool schema exceeds the discovery limit")
    return json.loads(encoded)


def _origin_for(client: Any) -> MCPOrigin:
    if hasattr(client, "url"):
        return MCPOrigin.HTTP
    if hasattr(client, "command"):
        return MCPOrigin.STDIO
    return MCPOrigin.UNKNOWN


class MCPToolDiscoveryBroker:
    """Discover and selectively invoke tools from an injected MCP client.

    ``refresh`` is deliberately explicit. Constructing the broker does not
    launch a subprocess or contact a remote HTTP server. This keeps normal
    agent startup and the legacy chat path side-effect free.
    """

    def __init__(
        self,
        client: Any,
        *,
        policy: MCPDiscoveryPolicy | None = None,
        max_servers: int = 64,
        max_tools: int = 512,
        max_result_bytes: int = 1_000_000,
    ) -> None:
        self.client = client
        self.policy = policy or MCPDiscoveryPolicy()
        self.max_servers = max(1, min(64, int(max_servers)))
        self.max_tools = max(1, min(2_048, int(max_tools)))
        self.max_result_bytes = max(1_024, min(8_000_000, int(max_result_bytes)))
        self._secret_scanner = SecretScanner()
        self._tools: dict[str, MCPToolDescriptor] = {}
        self._statuses: dict[str, MCPServerStatus] = {}

    @staticmethod
    def _qualified_name(server_name: str, tool_name: str) -> str:
        if not _NAME_RE.fullmatch(server_name) or not _NAME_RE.fullmatch(tool_name):
            raise MCPDiscoveryError("invalid MCP server or tool name")
        return f"{server_name}__{tool_name}"

    @staticmethod
    def _error_code(exc: Exception) -> str:
        text = str(exc).lower()
        if "timeout" in text or "zeitlimit" in text:
            return "timeout"
        if "auth" in text or "unauthor" in text or "forbidden" in text:
            return "authentication_required"
        return "unavailable"

    def _server_names(self, server_name: str | None) -> list[str]:
        servers = getattr(self.client, "servers", {})
        if not isinstance(servers, Mapping):
            raise MCPDiscoveryError("MCP client server registry unavailable")
        names = [str(server_name)] if server_name is not None else sorted(str(name) for name in servers)
        if len(names) > self.max_servers:
            raise MCPDiscoveryError("MCP discovery server limit exceeded")
        return [name for name in names if name in servers]

    def refresh(self, server_name: str | None = None) -> tuple[MCPServerStatus, ...]:
        """Explicitly fetch bounded tool metadata from one or all servers."""
        names = self._server_names(server_name)
        if server_name is not None and not names:
            raise MCPDiscoveryError("MCP server not found")
        for name in names:
            client = self.client.servers[name]
            origin = _origin_for(client)
            if origin.value not in self.policy.allowed_origins:
                self._statuses[name] = MCPServerStatus(name, origin, False, 0, "origin_not_allowed")
                continue
            if self.policy.allowed_servers is not None and name not in self.policy.allowed_servers:
                self._statuses[name] = MCPServerStatus(name, origin, False, 0, "server_not_allowed")
                continue
            try:
                raw_tools = client.list_tools()
                if not isinstance(raw_tools, list):
                    raise MCPDiscoveryError("invalid tools/list response")
                added = 0
                for raw in raw_tools:
                    if not isinstance(raw, Mapping):
                        continue
                    tool_name = str(raw.get("name") or "").strip()
                    if not _NAME_RE.fullmatch(tool_name):
                        continue
                    qualified = self._qualified_name(name, tool_name)
                    if self.policy.allowed_tools is not None and qualified not in self.policy.allowed_tools:
                        continue
                    schema = raw.get("inputSchema")
                    if not isinstance(schema, Mapping):
                        schema = {"type": "object", "properties": {}}
                    schema_copy = _bounded_json_value(schema)
                    checksum = hashlib.sha256(
                        json.dumps(schema_copy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest()
                    self._tools[qualified] = MCPToolDescriptor(
                        server_name=name,
                        tool_name=tool_name,
                        qualified_name=qualified,
                        description=str(raw.get("description") or "")[:_MAX_DESCRIPTION],
                        origin=origin,
                        schema_checksum=checksum,
                        input_schema=schema_copy,
                    )
                    added += 1
                    if len(self._tools) >= self.max_tools:
                        break
                self._statuses[name] = MCPServerStatus(name, origin, True, added)
            except Exception as exc:
                self._statuses[name] = MCPServerStatus(name, origin, False, 0, self._error_code(exc))
        return tuple(self._statuses[name] for name in names if name in self._statuses)

    def list_servers(self) -> tuple[dict[str, Any], ...]:
        return tuple(status.to_dict() for status in sorted(self._statuses.values(), key=lambda item: item.server_name))

    def search(self, query: str = "", *, limit: int = 20) -> tuple[dict[str, Any], ...]:
        """Return schema-free matching tools from the last explicit refresh."""
        clean_query = " ".join(str(query or "").casefold().split())
        terms = tuple(clean_query.split())
        bounded_limit = max(1, min(100, int(limit)))
        matches: list[dict[str, Any]] = []
        for tool in sorted(self._tools.values(), key=lambda item: item.qualified_name):
            if not self.policy.allows(tool):
                continue
            haystack = f"{tool.qualified_name} {tool.description}".casefold()
            if terms and not all(term in haystack for term in terms):
                continue
            matches.append(tool.summary())
            if len(matches) >= bounded_limit:
                break
        return tuple(matches)

    def describe(self, qualified_name: str) -> dict[str, Any]:
        tool = self._tools.get(str(qualified_name))
        if tool is None or not self.policy.allows(tool):
            raise MCPDiscoveryError("MCP tool is not available under the current policy")
        return tool.detail()

    def call(self, qualified_name: str, arguments: Mapping[str, Any]) -> Any:
        tool = self._tools.get(str(qualified_name))
        if tool is None or not self.policy.allows(tool, execute=True):
            return {
                "error": "MCP tool execution is not authorized",
                "status": "blocked",
                "tool_id": str(qualified_name),
            }
        if not isinstance(arguments, Mapping):
            return {"error": "MCP tool arguments must be an object", "status": "blocked"}
        try:
            result = self.client.servers[tool.server_name].call_tool(tool.tool_name, dict(arguments))
            encoded = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            if len(encoded) > self.max_result_bytes:
                return {
                    "error": "MCP tool result exceeds the result limit",
                    "status": "blocked",
                    "tool_id": tool.qualified_name,
                }
            if self._secret_scanner.scan(result):
                return {
                    "error": "MCP tool result contains a blocked secret pattern",
                    "status": "blocked",
                    "tool_id": tool.qualified_name,
                }
            return {"status": "completed", "tool_id": tool.qualified_name, "result": result}
        except Exception:
            return {"error": "MCP tool call failed", "status": "failed", "tool_id": tool.qualified_name}


__all__ = [
    "MCPDiscoveryError",
    "MCPDiscoveryPolicy",
    "MCPOrigin",
    "MCPServerStatus",
    "MCPToolDescriptor",
    "MCPToolDiscoveryBroker",
]
