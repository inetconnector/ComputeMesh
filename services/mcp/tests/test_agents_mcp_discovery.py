# SPDX-License-Identifier: Apache-2.0
"""Tests for the bounded external-MCP discovery boundary."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.mcp.mcp_client import MCPClient
from services.mcp.platform.mcp_discovery import (
    MCPDiscoveryError,
    MCPDiscoveryPolicy,
    MCPOrigin,
    MCPToolDiscoveryBroker,
)


class FakeMCPServer:
    command = "python"

    def __init__(self) -> None:
        self.list_calls = 0
        self.call_args: list[tuple[str, dict]] = []

    def list_tools(self):
        self.list_calls += 1
        return [
            {
                "name": "lookup",
                "description": "Look up a record",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {"name": "bad name", "description": "ignored"},
        ]

    def call_tool(self, name, arguments):
        self.call_args.append((name, arguments))
        return {"content": [{"type": "text", "text": "ok"}]}


class TestMCPToolDiscoveryBroker(unittest.TestCase):
    def _client(self, server=None):
        client = MCPClient()
        client.servers["catalog"] = server or FakeMCPServer()
        return client

    def test_construction_does_not_contact_server_and_search_omits_schema(self):
        server = FakeMCPServer()
        broker = MCPToolDiscoveryBroker(self._client(server))
        self.assertEqual(server.list_calls, 0)
        broker.refresh()
        self.assertEqual(server.list_calls, 1)
        matches = broker.search("lookup")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["tool_id"], "catalog__lookup")
        self.assertNotIn("input_schema", matches[0])
        detail = broker.describe("catalog__lookup")
        self.assertEqual(detail["origin"], MCPOrigin.STDIO.value)
        self.assertIn("input_schema", detail)
        self.assertEqual(len(detail["schema_checksum"]), 64)

    def test_default_policy_blocks_execution_until_explicitly_enabled(self):
        server = FakeMCPServer()
        broker = MCPToolDiscoveryBroker(self._client(server))
        broker.refresh()
        blocked = broker.call("catalog__lookup", {"query": "x"})
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(server.call_args, [])

        allowed = MCPToolDiscoveryBroker(
            self._client(server),
            policy=MCPDiscoveryPolicy(
                allowed_tools=frozenset({"catalog__lookup"}),
                allow_execution=True,
            ),
        )
        allowed.refresh()
        result = allowed.call("catalog__lookup", {"query": "x"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(server.call_args, [("lookup", {"query": "x"})])

    def test_policy_filters_origin_and_server_without_exposing_endpoint(self):
        server = SimpleNamespace(
            url="https://secret.example/mcp",
            list_tools=lambda: [{"name": "remote", "inputSchema": {"type": "object"}}],
        )
        broker = MCPToolDiscoveryBroker(
            self._client(server),
            policy=MCPDiscoveryPolicy(allowed_origins=frozenset({MCPOrigin.STDIO.value})),
        )
        statuses = broker.refresh()
        self.assertEqual(statuses[0].error_code, "origin_not_allowed")
        self.assertEqual(broker.search(), ())
        self.assertNotIn("secret.example", str(broker.list_servers()))

    def test_unknown_and_oversized_schemas_fail_closed(self):
        broker = MCPToolDiscoveryBroker(self._client())
        with self.assertRaises(MCPDiscoveryError):
            broker.describe("catalog__missing")

        server = SimpleNamespace(
            command="python",
            list_tools=lambda: [{"name": "huge", "inputSchema": {"x": "a" * 200_000}}],
        )
        broker = MCPToolDiscoveryBroker(self._client(server))
        statuses = broker.refresh()
        self.assertFalse(statuses[0].ready)
        self.assertEqual(statuses[0].error_code, "unavailable")

    def test_result_limit_and_secret_scan_never_return_raw_payload(self):
        server = FakeMCPServer()
        server.call_tool = lambda _name, _arguments: {"token": "Bearer abcdefghijklmnop"}
        broker = MCPToolDiscoveryBroker(
            self._client(server),
            policy=MCPDiscoveryPolicy(allow_execution=True),
        )
        broker.refresh()
        result = broker.call("catalog__lookup", {"query": "x"})
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("Bearer", str(result))


if __name__ == "__main__":
    unittest.main()
