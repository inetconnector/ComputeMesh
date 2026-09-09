# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded and synchronized external MCP stdio RPC."""

from __future__ import annotations

import io
import json
import subprocess
import time
import unittest
from unittest.mock import patch

from services.mcp.mcp_client import MCPStdioClient


class _FakeStdout:
    def __init__(self, lines=None, delay: float = 0.0):
        self.lines = list(lines or [])
        self.delay = delay
        self.closed = False

    def readline(self):
        if self.delay:
            time.sleep(self.delay)
        return self.lines.pop(0) if self.lines else ""

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, lines=None, delay: float = 0.0):
        self.stdin = io.StringIO()
        self.stdout = _FakeStdout(lines, delay=delay)
        self._returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._returncode

    def terminate(self):
        self.terminated = True
        self._returncode = 0

    def kill(self):
        self.killed = True
        self._returncode = -9

    def wait(self, timeout=None):
        return self._returncode


class TestMCPStdioHardening(unittest.TestCase):
    def test_rpc_ignores_notification_then_requires_matching_response(self):
        client = MCPStdioClient("demo", "python", rpc_timeout_seconds=1.0)
        client.process = _FakeProcess([
            json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}) + "\n",
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}) + "\n",
        ])
        result = client._send_rpc("ping", {})
        self.assertEqual(result, {"ok": True})
        sent = json.loads(client.process.stdin.getvalue().splitlines()[0])
        self.assertEqual(sent["id"], 1)
        self.assertEqual(sent["method"], "ping")

    def test_mismatched_response_id_is_protocol_error(self):
        client = MCPStdioClient("demo", "python", rpc_timeout_seconds=1.0)
        client.process = _FakeProcess([
            json.dumps({"jsonrpc": "2.0", "id": 99, "result": {}}) + "\n",
        ])
        with self.assertRaisesRegex(RuntimeError, "Antwort-ID"):
            client._send_rpc("ping", {})

    def test_blocking_stdout_is_bounded_by_timeout(self):
        client = MCPStdioClient("demo", "python", rpc_timeout_seconds=0.02)
        client.process = _FakeProcess(delay=0.2)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            client._send_rpc("ping", {})
        self.assertLess(time.monotonic() - started, 0.15)

    @patch("services.mcp.mcp_client.subprocess.Popen")
    def test_start_uses_devnull_stderr_and_handshake(self, popen):
        process = _FakeProcess([
            json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2026-07-28",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "demo", "version": "1"},
                },
            }) + "\n",
        ])
        popen.return_value = process
        client = MCPStdioClient("demo", "python", ["-m", "demo"], rpc_timeout_seconds=1.0)
        self.assertTrue(client.start())
        self.assertTrue(client._is_initialized)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        written = process.stdin.getvalue()
        self.assertIn('"method": "initialize"', written)
        self.assertIn('"method": "notifications/initialized"', written)

    def test_call_tool_failure_terminates_desynchronized_server(self):
        client = MCPStdioClient("demo", "python", rpc_timeout_seconds=0.02)
        process = _FakeProcess(delay=0.2)
        client.process = process
        client._is_initialized = True
        result = client.call_tool("tool", {})
        self.assertIn("RPC fehlgeschlagen", result["error"])
        self.assertTrue(process.terminated or process.killed)
        self.assertIsNone(client.process)


if __name__ == "__main__":
    unittest.main()
