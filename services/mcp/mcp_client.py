# SPDX-License-Identifier: Apache-2.0
"""MCP JSON-RPC 2.0 stdio client with bounded, serialized RPC calls."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

MCP_PROTOCOL_VERSION = "2026-07-28"
DEFAULT_RPC_TIMEOUT_SECONDS = 15.0


class MCPStdioClient:
    """Subprocess-based MCP client communicating over stdio JSON-RPC 2.0."""

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        rpc_timeout_seconds: float = DEFAULT_RPC_TIMEOUT_SECONDS,
    ):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {}) if env else None
        self.rpc_timeout_seconds = max(0.1, min(120.0, float(rpc_timeout_seconds)))
        self.process: Optional[subprocess.Popen] = None
        self._next_id = 1
        self._lifecycle_lock = threading.RLock()
        self._rpc_lock = threading.Lock()
        self._is_initialized = False

    def start(self) -> bool:
        with self._lifecycle_lock:
            if self.process is not None and self.process.poll() is None and self._is_initialized:
                return True
            if self.process is not None:
                self._terminate_process_locked()

            full_env = os.environ.copy()
            if self.env:
                full_env.update({str(key): str(value) for key, value in self.env.items()})

            try:
                self.process = subprocess.Popen(
                    [self.command] + self.args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    # Never leave an unread stderr pipe that can fill and deadlock
                    # the child. External MCP logs are not part of the JSON-RPC stream.
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                    env=full_env,
                )
            except (OSError, ValueError):
                self.process = None
                return False

            try:
                init_res = self._send_rpc("initialize", {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "ComputeMesh-MCP", "version": "1.2"},
                })
                if not isinstance(init_res, dict):
                    raise RuntimeError("Ungültige initialize-Antwort des MCP-Servers")
                self._send_notification("notifications/initialized", {})
                self._is_initialized = True
                return True
            except Exception:
                self._terminate_process_locked()
                return False

    def _terminate_process_locked(self) -> None:
        process = self.process
        self.process = None
        self._is_initialized = False
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2.0)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=1.0)
            except Exception:
                pass
        for stream_name in ("stdin", "stdout"):
            stream = getattr(process, stream_name, None)
            try:
                if stream:
                    stream.close()
            except Exception:
                pass

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._terminate_process_locked()

    def list_tools(self) -> List[Dict[str, Any]]:
        if not self._is_initialized and not self.start():
            return []
        try:
            res = self._send_rpc("tools/list", {})
        except Exception:
            self.stop()
            return []
        tools = res.get("tools") if isinstance(res, dict) else None
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if not self._is_initialized and not self.start():
            return {"error": f"MCP-Server '{self.name}' nicht gestartet"}
        try:
            return self._send_rpc("tools/call", {"name": name, "arguments": arguments})
        except Exception as exc:
            self.stop()
            return {"error": f"MCP-Server '{self.name}' RPC fehlgeschlagen: {exc}"}

    @staticmethod
    def _readline_with_timeout(stream: Any, timeout: float) -> str:
        result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def reader() -> None:
            try:
                result_queue.put((True, stream.readline()))
            except Exception as exc:
                result_queue.put((False, exc))

        thread = threading.Thread(target=reader, name="mcp-stdio-read", daemon=True)
        thread.start()
        try:
            ok, value = result_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("MCP-RPC Zeitlimit überschritten") from exc
        if not ok:
            raise RuntimeError(f"MCP-stdout konnte nicht gelesen werden: {value}")
        return str(value)

    def _send_rpc(self, method: str, params: Dict[str, Any]) -> Any:
        with self._rpc_lock:
            process = self.process
            if not process or process.poll() is not None or not process.stdin or not process.stdout:
                raise RuntimeError("MCP process not running")

            req_id = self._next_id
            self._next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except Exception as exc:
                raise RuntimeError(f"MCP-Request konnte nicht gesendet werden: {exc}") from exc

            deadline = time.monotonic() + self.rpc_timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("MCP-RPC Zeitlimit überschritten")
                resp_line = self._readline_with_timeout(process.stdout, remaining)
                if not resp_line:
                    raise RuntimeError("Leere Antwort vom MCP-Server")
                try:
                    data = json.loads(resp_line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("MCP-Server lieferte ungültiges JSON") from exc
                if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
                    raise RuntimeError("Ungültige JSON-RPC-Antwort vom MCP-Server")

                # Servers may emit notifications on stdout. Ignore only messages
                # without an id; an unexpected response id indicates desync.
                if "id" not in data:
                    continue
                if data.get("id") != req_id:
                    raise RuntimeError(
                        f"MCP-RPC Antwort-ID stimmt nicht überein (erwartet {req_id}, erhalten {data.get('id')})"
                    )
                if "error" in data:
                    raise RuntimeError(f"MCP RPC Error: {data['error']}")
                return data.get("result")

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        process = self.process
        if not process or process.poll() is not None or not process.stdin:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except Exception:
            pass


class MCPClient:
    """Manager for multiple external MCP servers and registry integration."""

    def __init__(self, config_path: str = ""):
        self.config_path = config_path
        self.servers: Dict[str, MCPStdioClient] = {}

    def add_stdio_server(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        rpc_timeout_seconds: float = DEFAULT_RPC_TIMEOUT_SECONDS,
    ) -> None:
        if not str(name or "").strip() or not str(command or "").strip():
            raise ValueError("MCP-Servername und command sind erforderlich")
        self.servers[str(name)] = MCPStdioClient(
            name=str(name),
            command=str(command),
            args=args,
            env=env,
            rpc_timeout_seconds=rpc_timeout_seconds,
        )

    def load_from_config(self, filepath: str) -> None:
        if not filepath or not os.path.exists(filepath):
            return
        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        mcp_servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
        if not isinstance(mcp_servers, dict):
            return

        for name, srv_data in mcp_servers.items():
            if not isinstance(srv_data, dict):
                continue
            command = srv_data.get("command")
            args = srv_data.get("args", [])
            env = srv_data.get("env", {})
            timeout = srv_data.get("timeoutSeconds", DEFAULT_RPC_TIMEOUT_SECONDS)
            if not isinstance(command, str) or not command.strip():
                continue
            if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
                continue
            if not isinstance(env, dict):
                continue
            try:
                self.add_stdio_server(
                    str(name), command=command, args=args, env=env,
                    rpc_timeout_seconds=float(timeout),
                )
            except (TypeError, ValueError):
                continue

    def register_all_into_registry(self, registry: Any) -> None:
        for srv_name, client in self.servers.items():
            tools = client.list_tools()
            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                original_name = tool.get("name")
                if not isinstance(original_name, str) or not original_name.strip():
                    continue
                description = tool.get("description", "")
                params = tool.get("inputSchema", {"type": "object", "properties": {}})
                if not isinstance(params, dict):
                    params = {"type": "object", "properties": {}}

                def make_handler(c: MCPStdioClient = client, orig_name: str = original_name):
                    return lambda **kwargs: c.call_tool(orig_name, kwargs)

                registry.register_tool(
                    name=f"{srv_name}__{original_name}",
                    description=str(description or ""),
                    parameters=params,
                    handler=make_handler(),
                    owner_only=True,
                    source=f"mcp:{srv_name}",
                )
