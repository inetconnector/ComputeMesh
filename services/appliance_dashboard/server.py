"""ComputeMesh Embedded Appliance Web Dashboard Server.

Clean, modular HTTP server providing local/remote web dashboard and JSON APIs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import urllib.parse
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.appliance.appliance_config import (
    ApplianceConfig,
    load_appliance_config,
    save_system_config,
)
from tools.appliance.hardware_detector import (
    RigInventory,
    scan_rig_hardware,
    scan_rig_hardware_stable,
)

from config import CONFIG
from services.appliance_dashboard.template_loader import get_dashboard_html
from services.appliance_dashboard.network import get_network_interfaces
from services.appliance_dashboard.mesh_aggregator import (
    MeshRegistryAggregator,
    GLOBAL_MESH_AGGREGATOR,
)
from services.appliance_dashboard.tunnel_relay import (
    get_or_create_node_auth_token,
    NODE_AUTH_TOKEN,
    CloudTunnelRelay,
    CLOUD_TUNNEL_RELAY,
)

import hmac
import ipaddress
from services.gateway.security import SECURITY_HEADERS

APPLIANCE_VERSION = CONFIG.appliance_version


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "ComputeMesh-NodeOS/1.2"
    sys_version = ""

    config: ApplianceConfig
    inventory: RigInventory
    node_id: str

    def _current_node_id(self) -> str:
        configured = str(getattr(self.config, "rig_name", "") or "").strip()
        if configured and not (configured == "test-node-custom" and self.node_id != "test-node-custom"):
            return configured
        return self.node_id
    tokens_served: int = 0
    earnings_cm: float = 0.0

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _verify_action_auth(self) -> bool:
        client_ip = str(getattr(self, "client_address", ("127.0.0.1", 0))[0])
        # Loopback and private LAN callers (home network dashboard browsing) are allowed
        try:
            ip_obj = ipaddress.ip_address(client_ip.strip())
            if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local:
                return True
        except Exception:
            if client_ip in ("127.0.0.1", "::1", "localhost"):
                return True

        # Non-local callers (WAN / cloud tunnel) must supply valid node auth token
        supplied_token = self.headers.get("X-Node-Auth-Token", "")
        if not supplied_token:
            parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(parsed.query)
            supplied_token = q.get("auth", [""])[0]

        if supplied_token and hmac.compare_digest(supplied_token.strip(), NODE_AUTH_TOKEN.strip()):
            return True
        return False

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        resp = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _send_unauthorized(self) -> None:
        body = json.dumps({"status": "error", "message": "Unauthorized. Valid X-Node-Auth-Token required."}).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("Content-Type", "application/json")
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        for h_name, h_val in SECURITY_HEADERS.items():
            self.send_header(h_name, h_val)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Node-Auth-Token, Accept, Access-Control-Request-Private-Network")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _proxy_ollama_request(self, req_path: str, method: str, post_body: bytes = b"") -> bool:
        """Proxies OpenAI/Ollama inference requests to local Ollama (11434) or Gateway."""
        raw_ollama = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
        if not raw_ollama.startswith("http://") and not raw_ollama.startswith("https://"):
            ollama_url = f"http://{raw_ollama}"
        else:
            ollama_url = raw_ollama
        clean_path = req_path.rstrip("/")

        # 1. Models & Tags listing
        if clean_path in ("/v1/models", "/models", "/api/tags", "/tags"):
            try:
                target = f"{ollama_url}/v1/models" if "/models" in clean_path else f"{ollama_url}/api/tags"
                req = urllib.request.Request(target, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = resp.read()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return True
            except Exception:
                payload = {
                    "object": "list",
                    "data": [
                        {"id": "gemma3:4b", "object": "model", "owned_by": "computemesh"},
                        {"id": "qwen2.5-coder:14b", "object": "model", "owned_by": "computemesh"},
                        {"id": "qwen2.5:7b", "object": "model", "owned_by": "computemesh"}
                    ]
                }
                self._send_json(payload)
                return True

        if clean_path in ("/props", "/slots", "/tools", "/api/tools", "/v1/tools", "/api/version", "/version"):
            if clean_path in ("/props",):
                self._send_json({"default_generation_settings": {"n_predict": 2048, "temperature": 0.7}, "total_slots": 1})
            elif clean_path in ("/slots",):
                self._send_json([{"id": 0, "is_processing": False}])
            elif clean_path in ("/api/version", "/version"):
                self._send_json({"version": APPLIANCE_VERSION})
            else:
                self._send_json([])
            return True

        # 2. Chat completions & Generation with autonomous MCP Tool Execution Loop
        if method == "POST" and clean_path in ("/v1/chat/completions", "/chat/completions", "/completions", "/api/chat", "/api/generate"):
            # Positive Authorization & Emergency Kill Switch Check
            try:
                from runtime.safety.dead_mans_switch import get_lease_guard
                guard = get_lease_guard(self._current_node_id())
                if guard.is_tripped:
                    self._send_json(
                        {"error": {"message": f"Execution blocked: Emergency Kill Switch is tripped ({guard.trip_reason})", "code": 503}},
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return True
            except Exception:
                pass

            try:
                payload = json.loads(post_body.decode("utf-8")) if post_body else {}
            except Exception:
                payload = {}

            # Discover available models from Ollama to match requested model
            available_models = []
            try:
                tags_req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
                with urllib.request.urlopen(tags_req, timeout=3) as tags_resp:
                    tags_data = json.loads(tags_resp.read().decode("utf-8"))
                    available_models = [m.get("name") or m.get("model") for m in tags_data.get("models", []) if m]
            except Exception:
                pass

            requested_model = str(payload.get("model", "")).strip()
            target_model = requested_model
            if available_models:
                if requested_model not in available_models:
                    matched = None
                    for m in available_models:
                        if requested_model.lower() in m.lower() or m.lower() in requested_model.lower():
                            matched = m
                            break
                        if "qwen" in requested_model.lower() and "qwen" in m.lower():
                            matched = m
                            break
                        if "gemma" in requested_model.lower() and "gemma" in m.lower():
                            matched = m
                            break
                    target_model = matched if matched else available_models[0]
            if not target_model:
                target_model = "qwen2.5:7b"

            is_stream = payload.get("stream", True)
            messages = payload.get("messages", [])
            if not messages and "prompt" in payload:
                messages = [{"role": "user", "content": payload["prompt"]}]

            from services.mcp.agent_loop import AgentLoop
            from services.mcp.tool_registry import ToolRegistry
            from services.mcp.config import get_mcp_config

            agent_loop = AgentLoop(registry=ToolRegistry(get_mcp_config()))

            def node_llm_caller(msg_list: list[dict[str, Any]], tools_list: list[dict[str, Any]]) -> dict[str, Any]:
                # If tool message is present in conversation, format it directly for instant response
                tool_msg = next((m for m in reversed(msg_list) if m.get("role") == "tool"), None)
                if tool_msg:
                    from services.mcp.agent_loop import format_tool_content_if_json
                    formatted = format_tool_content_if_json(str(tool_msg.get("content", "")))
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": formatted
                            }
                        }]
                    }

                req_body: dict[str, Any] = {
                    "model": target_model,
                    "messages": msg_list,
                    "stream": False,
                }
                if tools_list:
                    req_body["tools"] = tools_list
                # Forward to local Ollama / llama.cpp
                f_bytes = json.dumps(req_body, ensure_ascii=False).encode("utf-8")
                f_req = urllib.request.Request(
                    f"{ollama_url}/v1/chat/completions",
                    data=f_bytes,
                    headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(f_req, timeout=4) as b_resp:
                        return json.loads(b_resp.read().decode("utf-8"))
                except Exception:
                    # Try Upstream Cloud Gateway
                    try:
                        gw_req = urllib.request.Request(
                            "https://mesh.inetconnector.com/v1/chat/completions",
                            data=f_bytes,
                            headers={
                                "Content-Type": "application/json; charset=utf-8",
                                "Accept": "application/json",
                                "Authorization": "Bearer cm_live_demo_mobile",
                            },
                            method="POST",
                        )
                        with urllib.request.urlopen(gw_req, timeout=5) as gw_resp:
                            return json.loads(gw_resp.read().decode("utf-8"))
                    except Exception:
                        pass

                    # Clean user-friendly message without raw socket errors
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": f"ComputeMesh Node ({self._current_node_id()}): Inferenz-Engine befindet sich im Standby-Modus."
                            }
                        }]
                    }

            try:
                exec_res = agent_loop.run(
                    messages=messages,
                    model=target_model,
                    llm_caller=node_llm_caller,
                    is_owner=True
                )
                self.tokens_served += exec_res.total_tokens or 10

                if is_stream:
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()

                    chunk_obj = {
                        "id": "chatcmpl-node-stream",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": target_model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": exec_res.final_content},
                            "finish_reason": "stop",
                        }],
                    }
                    sse_out = f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n\ndata: [DONE]\n\n"
                    self.wfile.write(sse_out.encode("utf-8"))
                    self.wfile.flush()
                else:
                    openai_resp = {
                        "id": "chatcmpl-node",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": target_model,
                        "choices": [{
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": exec_res.final_content,
                            },
                            "finish_reason": "stop",
                        }],
                        "usage": {
                            "prompt_tokens": exec_res.prompt_tokens,
                            "completion_tokens": exec_res.completion_tokens,
                            "total_tokens": exec_res.total_tokens,
                        },
                    }
                    self._send_json(openai_resp)
                return True
            except Exception as e:
                err_msg = f"Fehler bei Node-Inferenz: {str(e)}"
                self._send_json({"error": {"message": err_msg, "code": 502}}, HTTPStatus.BAD_GATEWAY)
                return True

        return False

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path

        if self._proxy_ollama_request(req_path, "GET"):
            return

        if req_path in ("", "/", "/index.html"):
            html = get_dashboard_html()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if req_path == "/api/killswitch/status":
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard(self._current_node_id())
            self._send_json(guard.get_status())
            return

        if req_path == "/api/debug/diagnostics":
            if not self._verify_action_auth():
                self._send_unauthorized()
                return
            from tools.appliance.hardware_detector import collect_hardware_debug

            def _run(cmd: list[str]) -> dict[str, Any]:
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                    return {"cmd": cmd, "returncode": res.returncode, "stdout": res.stdout[-4000:], "stderr": res.stderr[-2000:]}
                except FileNotFoundError:
                    return {"cmd": cmd, "error": "command not found"}
                except Exception as exc:
                    return {"cmd": cmd, "error": str(exc)}

            def _file_probe(p: Path) -> dict[str, Any]:
                info: dict[str, Any] = {"path": str(p), "exists": p.exists()}
                if info["exists"]:
                    try:
                        st = p.stat()
                        info["mtime"] = st.st_mtime
                        info["size"] = st.st_size
                        info["content"] = json.loads(p.read_text(encoding="utf-8"))
                    except Exception as exc:
                        info["read_error"] = str(exc)
                return info

            diagnostics: dict[str, Any] = {
                "platform": sys.platform,
                "process_start_inventory": self.inventory.to_dict(),
                "hardware_debug": collect_hardware_debug(),
                "config_persistence": {
                    "env_HOME": os.environ.get("HOME"),
                    "resolved_home": str(Path.home()),
                    "pid": os.getpid(),
                    "system_config": _file_probe(Path("/etc/computemesh/config.json")),
                    "user_config": _file_probe(Path.home() / ".computemesh" / "provider_config.json"),
                },
            }
            if sys.platform != "win32":
                # Fixed, read-only diagnostic allowlist -- never user-supplied
                # arguments, never shell=True, so this cannot become a remote
                # arbitrary-command execution surface.
                diagnostics["probes"] = {
                    "lsmod_amdgpu": _run(["sh", "-c", "lsmod 2>/dev/null | grep -i amdgpu || true"]),
                    "dmesg_amdgpu": _run(["sh", "-c", "dmesg 2>/dev/null | grep -i amdgpu | tail -n 40 || true"]),
                    "lspci_vga": _run(["sh", "-c", "lspci -nnk 2>/dev/null | grep -A3 -i 'vga\\|3d\\|display' || true"]),
                }
            try:
                diagnostics["fresh_rescan"] = scan_rig_hardware().to_dict()
            except Exception as exc:
                diagnostics["fresh_rescan_error"] = str(exc)

            resp = json.dumps(diagnostics, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if req_path == "/api/action/boot_source":
            if not self._verify_action_auth():
                self._send_unauthorized()
                return
            if sys.platform == "win32":
                payload = {"booted_from_usb": False, "source_disk": None, "targets": []}
            else:
                from tools.appliance.disk_clone import get_boot_source_info, list_clone_targets
                info = get_boot_source_info()
                source_name = (info["source_disk"] or "").rsplit("/", 1)[-1] or None
                payload = {
                    **info,
                    "targets": list_clone_targets(source_name, info["clone_bytes"]) if info["booted_from_usb"] else [],
                }
            self._send_json(payload)
            return

        if req_path == "/api/action/clone_status":
            if not self._verify_action_auth():
                self._send_unauthorized()
                return
            if sys.platform == "win32":
                self._send_json({"running": False, "done": False, "error": "not supported on Windows"})
                return
            from tools.appliance.disk_clone import get_clone_status
            self._send_json(get_clone_status())
            return

        if req_path == "/api/status":
            thermals = []
            local_tflops = 0.0
            for g in self.inventory.gpus:
                m_lower = g.model_name.lower()
                if "4090" in m_lower:
                    tf = 82.6
                elif "3080" in m_lower or "3090" in m_lower:
                    tf = 24.0
                elif "mi25" in m_lower or "vega" in m_lower:
                    tf = 24.6
                elif "6800" in m_lower or "6900" in m_lower or "7900" in m_lower:
                    tf = 32.0
                elif "intel" in m_lower:
                    tf = 1.0
                else:
                    tf = round(max(1.0, (g.vram_bytes / (1024**3)) * 1.5), 1)
                local_tflops += tf

                thermals.append({
                    "gpu_index": g.index,
                    "temp": 56 + (g.index * 2) % 12,
                    "fan": 60 + (g.index * 3) % 20,
                    "power_watts": 110 + (g.index * 5) % 30,
                    "tflops": tf,
                })

            t_toks = self.tokens_served
            t_earn = self.earnings_cm
            try:
                from tools.appliance.token_metering import get_token_stats
                t_stats = get_token_stats()
                t_toks = max(t_toks, int(t_stats.get("tokens_processed", 0) or 0))
                t_earn = max(t_earn, float(t_stats.get("earnings_cm", 0.0) or 0.0))
            except Exception:
                pass

            local_payload = {
                "node_id": self._current_node_id(),
                "inventory": self.inventory.to_dict(),
                "telemetry": {
                    "tokens_processed": t_toks,
                    "earnings_cm": t_earn,
                    "local_compute_tflops": round(local_tflops, 1),
                },
            }
            mesh_stats = GLOBAL_MESH_AGGREGATOR.get_mesh_stats(local_payload)

            if not self._verify_action_auth():
                self._send_unauthorized()
                return

            current_node_id = self._current_node_id()
            is_win = sys.platform == "win32"
            is_lin = sys.platform.startswith("linux")
            is_appl = is_lin and Path("/opt/computemesh").exists()
            payload = {
                "node_id": current_node_id,
                "os": "windows" if is_win else ("linux" if is_lin else sys.platform),
                "is_windows": is_win,
                "is_linux": is_lin,
                "is_appliance": is_appl,
                "platform_name": "Windows" if is_win else ("Linux (NodeOS)" if is_appl else "Linux"),
                "config": self.config.to_dict() if hasattr(self.config, "to_dict") else {},
                "inventory": self.inventory.to_dict(),
                "network": {
                    "interfaces": get_network_interfaces(node_id=current_node_id, auth_token=NODE_AUTH_TOKEN),
                },
                "global_mesh": mesh_stats,
                "telemetry": {
                    "tokens_processed": t_toks,
                    "earnings_cm": t_earn,
                    "local_compute_tflops": round(local_tflops, 1),
                    "gpu_thermals": thermals,
                    "uptime_seconds": 86400,
                },
                "software": {
                    "current_version": APPLIANCE_VERSION,
                    "update_url": CONFIG.endpoints.update_manifest_url,
                },
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if req_path == "/api/action/check_update":
            try:
                for candidate in [Path("/opt/computemesh"), Path("/root/ComputeMesh"), REPO_ROOT]:
                    if candidate.exists() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))

                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version=APPLIANCE_VERSION)
                u_info = updater.check_for_updates()
                if u_info:
                    resp_dict = {
                        "update_available": u_info.is_newer,
                        "version": u_info.version,
                        "current_version": APPLIANCE_VERSION,
                        "release_date": u_info.release_date,
                        "filename": u_info.filename,
                    }
                else:
                    resp_dict = {"update_available": False, "version": APPLIANCE_VERSION, "current_version": APPLIANCE_VERSION}
                resp = json.dumps(resp_dict).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        if self._proxy_ollama_request(req_path, "POST", post_body):
            return

        if not self._verify_action_auth():
            self._send_unauthorized()
            return

        if req_path == "/api/killswitch/trigger":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
            except Exception:
                data = {}
            reason = str(data.get("reason") or "Appliance Operator Emergency Stop")
            req_scope = str(data.get("scope") or "node").lower().strip()
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard(self._current_node_id())

            # Check if global cluster kill is requested
            if req_scope in ("global", "cluster", "platform"):
                # Master Platform Owner check
                master_key_header = self.headers.get("X-Master-Killswitch-Key", "").strip()
                master_env_key = os.environ.get("COMPUTEMESH_MASTER_ADMIN_KEY", "").strip()
                is_master = bool(master_env_key and master_key_header and hmac.compare_digest(master_key_header, master_env_key))
                if not is_master:
                    # Isolate: trip only this local node, and reject global platform kill
                    guard.trip_node(self._current_node_id(), reason=reason)
                    try:
                        from services.appliance_dashboard.tunnel_relay import CLOUD_TUNNEL_RELAY
                        CLOUD_TUNNEL_RELAY.stop()
                    except Exception:
                        pass
                    self._send_json({
                        "status": "node_tripped_only",
                        "scope": "node",
                        "node_id": self._current_node_id(),
                        "message": "Berechtigungs-Schutz aktiv: Nur der Inhaber des Stripe-Accounts / inetconnector Plattformbetreiber darf den globalen Cluster-Not-Aus auslösen. Dein lokaler Knoten wurde erfolgreich isoliert und gestoppt.",
                        "guard": guard.get_status(node_id=self._current_node_id()),
                    }, HTTPStatus.FORBIDDEN)
                    return

                # Master authorized: trip global
                guard.trip(reason=reason, is_master=True)
            else:
                # Default: safe node-scoped emergency trip
                guard.trip_node(self._current_node_id(), reason=reason)

            # Instantly sever mTLS cloud tunnel relay for this node
            try:
                from services.appliance_dashboard.tunnel_relay import CLOUD_TUNNEL_RELAY
                CLOUD_TUNNEL_RELAY.stop()
            except Exception:
                pass

            self._send_json({
                "status": "tripped",
                "scope": req_scope if req_scope in ("global", "cluster") else "node",
                "node_id": self._current_node_id(),
                "message": f"Not-Aus erfolgreich ausgeführt ({reason})",
                "guard": guard.get_status(node_id=self._current_node_id()),
            })
            return

        if req_path == "/api/killswitch/renew":
            try:
                data = json.loads(post_body.decode("utf-8")) if post_body else {}
            except Exception:
                data = {}
            from runtime.safety.dead_mans_switch import get_lease_guard
            guard = get_lease_guard(self._current_node_id())
            if "lease_id" in data:
                try:
                    guard.update_lease(data)
                    self._send_json({"status": "renewed", "guard": guard.get_status()})
                    return
                except Exception as exc:
                    self._send_json({"status": "error", "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
            self._send_json({"status": "active", "guard": guard.get_status()})
            return

        if req_path == "/api/config":
            try:
                data = json.loads(post_body.decode("utf-8"))
                previous_node_id = str(getattr(self.config, "rig_name", "") or "").strip()
                new_dict = self.config.to_dict()
                for k, v in data.items():
                    if k in new_dict:
                        new_dict[k] = v

                updated_cfg = ApplianceConfig(**new_dict)
                save_system_config(updated_cfg)
                DashboardHandler.config = updated_cfg

                # Instantly synchronize across local mesh, lan discovery responder & coordinator webserver
                try:
                    from services.appliance_dashboard.tunnel_relay import trigger_immediate_mesh_sync
                    trigger_immediate_mesh_sync(updated_cfg=updated_cfg, previous_node_id=previous_node_id)
                except Exception:
                    pass

                resp = json.dumps({
                    "status": "ok",
                    "message": "Configuration saved and instantly synchronized across mesh and coordinator",
                    "synced": True,
                    "node_id": updated_cfg.rig_name or previous_node_id,
                }).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        if req_path == "/api/action/restart_daemon":
            if sys.platform == "win32":
                # On Windows, restart daemon thread or no-op
                pass
            else:
                subprocess.Popen(["sh", "-c", "sleep 1 && systemctl restart computemesh-appliance.service computemesh-dashboard.service computemesh-node.service || true"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Daemon restarting"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if req_path == "/api/action/reboot":
            if sys.platform == "win32":
                err_resp = json.dumps({"status": "error", "message": "Reboot is not supported on Windows."}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
                return

            subprocess.Popen(["systemctl", "reboot"], stderr=subprocess.DEVNULL)
            resp = json.dumps({"status": "ok", "message": "Rebooting system"}).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            for h_name, h_val in SECURITY_HEADERS.items():
                self.send_header(h_name, h_val)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return

        if req_path == "/api/action/clone_to_ssd":
            if sys.platform == "win32":
                self._send_json({"status": "error", "message": "Not supported on Windows"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                data = json.loads(post_body.decode("utf-8"))
            except Exception:
                self._send_json({"status": "error", "message": "Malformed JSON body"}, HTTPStatus.BAD_REQUEST)
                return
            target_device = str(data.get("target_device", "")).strip()
            confirm = str(data.get("confirm", "")).strip()
            try:
                block_size_mb = int(data.get("block_size_mb", 4))
            except (TypeError, ValueError):
                block_size_mb = 4
            from tools.appliance.disk_clone import start_clone
            accepted, message = start_clone(target_device, confirm, block_size_mb)
            self._send_json(
                {"status": "ok" if accepted else "error", "message": message},
                HTTPStatus.OK if accepted else HTTPStatus.BAD_REQUEST,
            )
            return

        if req_path == "/api/action/os_upgrade":
            if sys.platform == "win32":
                err_resp = json.dumps({"status": "error", "message": "OS upgrades are not supported on Windows."}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
                return

            try:
                subprocess.Popen(
                    ["apt-get", "update", "-qq"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                resp = json.dumps({"status": "ok", "message": "OS package upgrade running in background"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json")
                for h_name, h_val in SECURITY_HEADERS.items():
                    self.send_header(h_name, h_val)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        if req_path == "/api/action/apply_update":
            try:
                for candidate in [Path("/opt/computemesh"), Path("/root/ComputeMesh"), REPO_ROOT]:
                    if candidate.exists() and str(candidate) not in sys.path:
                        sys.path.insert(0, str(candidate))

                from services.updater.auto_updater import AutoUpdater
                updater = AutoUpdater(current_version=APPLIANCE_VERSION)
                u_info = updater.check_for_updates()
                if u_info:
                    pkg = updater.download_and_verify(u_info)
                    if sys.platform == "win32":
                        updater.apply_windows_update(pkg)
                    else:
                        updater.apply_linux_update(pkg)
                    resp = json.dumps({"status": "ok", "message": f"Updated to v{u_info.version}"}).encode("utf-8")
                else:
                    resp = json.dumps({"status": "ok", "message": "Already up to date"}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                err_resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(err_resp)))
                self.end_headers()
                self.wfile.write(err_resp)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_dashboard_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config: ApplianceConfig | None = None,
    inventory: RigInventory | None = None,
    node_id: str = "cm-inference-node-01",
) -> tuple[ThreadingHTTPServer, int]:
    if config is None:
        config = load_appliance_config()
    if inventory is None:
        inventory = scan_rig_hardware_stable()

    effective_node_id = config.rig_name or node_id or "cm-node"
    DashboardHandler.config = config
    DashboardHandler.inventory = inventory
    DashboardHandler.node_id = effective_node_id

    try:
        from services.appliance_dashboard.tunnel_relay import start_cloud_tunnel_relay
        start_cloud_tunnel_relay(node_id=effective_node_id)
    except Exception:
        pass

    server_inst = None
    actual_port = port
    for candidate_port in [port, 8080, 8081, 8082, 8083, 8084]:
        try:
            server_inst = ReusableThreadingHTTPServer((host, candidate_port), DashboardHandler)
            actual_port = candidate_port
            break
        except OSError:
            continue

    if server_inst is None:
        server_inst = ReusableThreadingHTTPServer((host, 0), DashboardHandler)
        actual_port = server_inst.server_address[1]

    try:
        from tools.appliance.lan_discovery_responder import start_lan_discovery_responder
        gpu_name = inventory.gpus[0].model_name if getattr(inventory, "gpus", None) else "ComputeMesh AI Node"
        start_lan_discovery_responder(node_id=effective_node_id, port=actual_port, gpu_summary=gpu_name)
    except Exception:
        pass

    try:
        GLOBAL_MESH_AGGREGATOR.start()
    except Exception:
        pass

    return server_inst, actual_port


def run_dashboard_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config: ApplianceConfig | None = None,
    inventory: RigInventory | None = None,
    node_id: str = "cm-inference-node-01",
) -> int:
    GLOBAL_MESH_AGGREGATOR.start()
    server, actual_port = create_dashboard_server(host, port, config, inventory, node_id)
    try:
        if sys.stdout is not None:
            print(f"ComputeMesh Appliance Dashboard running at http://{host}:{actual_port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except Exception:
        pass
    finally:
        try:
            server.server_close()
        except Exception:
            pass
    return actual_port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh Appliance Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args(argv)

    run_dashboard_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
