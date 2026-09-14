# SPDX-License-Identifier: Apache-2.0
"""HTTP / Server-Sent Events (SSE) JSON-RPC 2.0 Client for remote MCP servers."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("computemesh.mcp.http_client")

MCP_PROTOCOL_VERSION = "2026-07-28"
DEFAULT_HTTP_TIMEOUT = 15.0


class MCPHttpClient:
    """Client for remote MCP servers communicating over HTTP / SSE JSON-RPC 2.0."""

    def __init__(
        self,
        name: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT,
    ):
        self.name = str(name).strip()
        self.url = str(url).strip()
        self.headers = dict(headers or {})
        self.timeout_seconds = max(0.5, min(120.0, float(timeout_seconds)))
        self._next_id = 1
        self._is_initialized = False

    def _send_rpc(self, method: str, params: Dict[str, Any]) -> Any:
        req_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "ComputeMesh-MCP-HTTP/1.2",
            **self.headers,
        }
        req = urllib.request.Request(self.url, data=body_bytes, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                resp_bytes = resp.read()
                resp_text = resp_bytes.decode("utf-8")
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {err.code}: {err_body or err.reason}")
        except Exception as exc:
            raise RuntimeError(f"Verbindungsfehler zu MCP-Server '{self.name}': {exc}")

        # If response is SSE event stream, find data line
        clean_text = resp_text.strip()
        if "data:" in clean_text:
            lines = clean_text.splitlines()
            for line in lines:
                if line.startswith("data:"):
                    clean_text = line[len("data:"):].strip()
                    break

        try:
            data = json.loads(clean_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ungültige JSON-Antwort von '{self.name}': {exc}")

        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
            raise RuntimeError(f"Ungültige JSON-RPC 2.0 Struktur von '{self.name}'")
        if "error" in data:
            raise RuntimeError(f"MCP RPC Fehler: {data['error']}")
        return data.get("result")

    def initialize(self) -> bool:
        try:
            res = self._send_rpc("initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "ComputeMesh-MCP-Client", "version": "1.2"},
            })
            if isinstance(res, dict):
                self._is_initialized = True
                return True
        except Exception as exc:
            log.warning(f"MCP-Server '{self.name}' Initialisierung fehlgeschlagen: {exc}")
        return False

    def list_tools(self) -> List[Dict[str, Any]]:
        if not self._is_initialized and not self.initialize():
            return []
        try:
            res = self._send_rpc("tools/list", {})
            if isinstance(res, dict) and isinstance(res.get("tools"), list):
                return res["tools"]
        except Exception as exc:
            log.warning(f"tools/list auf '{self.name}' fehlgeschlagen: {exc}")
        return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if not self._is_initialized and not self.initialize():
            return {"error": f"MCP-Server '{self.name}' nicht initialisiert"}
        try:
            return self._send_rpc("tools/call", {"name": name, "arguments": arguments})
        except Exception as exc:
            return {"error": f"MCP-Server '{self.name}' Aufruf fehlgeschlagen: {exc}"}
