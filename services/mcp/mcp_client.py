# SPDX-License-Identifier: Apache-2.0
"""
Standard Model Context Protocol (MCP) Client Implementation (JSON-RPC 2.0 / Stdio & SSE Transport).
Ported and enhanced from LocalCode/src/mcp.go and mcp_builtin.go.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional

MCP_PROTOCOL_VERSION = "2026-07-28"


class MCPStdioClient:
    """
    Subprocess-based MCP Client communicating over standard input/output with JSON-RPC 2.0.
    """

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self.process: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._is_initialized = False

    def start(self) -> bool:
        with self._lock:
            if self.process is not None:
                return True

            full_env = os.environ.copy()
            if self.env:
                full_env.update(self.env)

            cmd_list = [self.command] + self.args
            try:
                self.process = subprocess.Popen(
                    cmd_list,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    env=full_env,
                )
            except Exception:
                self.process = None
                return False

            # Run MCP initialize handshake
            try:
                init_res = self._send_rpc("initialize", {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "ComputeMesh-MCP", "version": "1.2"},
                })
                if init_res:
                    self._send_notification("notifications/initialized", {})
                    self._is_initialized = True
                    return True
            except Exception:
                self.stop()
                return False

            return False

    def stop(self) -> None:
        with self._lock:
            if self.process:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2.0)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
                self.process = None
            self._is_initialized = False

    def list_tools(self) -> List[Dict[str, Any]]:
        if not self._is_initialized and not self.start():
            return []

        res = self._send_rpc("tools/list", {})
        if isinstance(res, dict) and "tools" in res:
            return res["tools"]
        return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if not self._is_initialized and not self.start():
            return {"error": f"MCP-Server '{self.name}' nicht gestartet"}

        res = self._send_rpc("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        return res

    def _send_rpc(self, method: str, params: Dict[str, Any]) -> Any:
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP process not running")

        req_id = self._next_id
        self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        line = json.dumps(payload) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

        # Read JSON-RPC response line
        resp_line = self.process.stdout.readline()
        if not resp_line:
            raise RuntimeError("Empty response from MCP server")

        data = json.loads(resp_line.strip())
        if "error" in data:
            raise RuntimeError(f"MCP RPC Error: {data['error']}")
        return data.get("result")

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        line = json.dumps(payload) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()


class MCPClient:
    """
    Manager for multiple MCP servers and integration with ComputeMesh ToolRegistry.
    """

    def __init__(self, config_path: str = ""):
        self.config_path = config_path
        self.servers: Dict[str, MCPStdioClient] = {}

    def add_stdio_server(self, name: str, command: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> None:
        self.servers[name] = MCPStdioClient(name=name, command=command, args=args, env=env)

    def load_from_config(self, filepath: str) -> None:
        if not filepath or not os.path.exists(filepath):
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            mcp_servers = data.get("mcpServers", {})
            for name, srv_data in mcp_servers.items():
                cmd = srv_data.get("command")
                args = srv_data.get("args", [])
                env = srv_data.get("env", {})
                if cmd:
                    self.add_stdio_server(name, command=cmd, args=args, env=env)
        except Exception:
            pass

    def register_all_into_registry(self, registry: Any) -> None:
        for srv_name, client in self.servers.items():
            try:
                tools = client.list_tools()
                for t in tools:
                    t_name = f"{srv_name}__{t.get('name')}"
                    t_desc = t.get("description", "")
                    t_params = t.get("inputSchema", {"type": "object", "properties": {}})

                    def make_handler(c=client, orig_name=t.get("name")):
                        return lambda **kwargs: c.call_tool(orig_name, kwargs)

                    registry.register_tool(
                        name=t_name,
                        description=t_desc,
                        parameters=t_params,
                        handler=make_handler(),
                        owner_only=True,
                        source=f"mcp:{srv_name}",
                    )
            except Exception:
                pass
