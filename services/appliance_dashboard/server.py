"""ComputeMesh Embedded Appliance Web Dashboard Server.

Clean, modular HTTP server delegating to specialized routers and sub-handlers.
"""
from __future__ import annotations

import argparse
import hmac
import io
import ipaddress
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

from cm_project_bootstrap import REPO_ROOT
from config import CONFIG
from services.appliance_dashboard import tunnel_relay as _tunnel_relay
from services.appliance_dashboard.fan_control_handler import FanControlHandler
from services.appliance_dashboard.inference_router import InferenceRouter
from services.appliance_dashboard.killswitch_actions import KillswitchHandler
from services.appliance_dashboard.mesh_aggregator import (
    GLOBAL_MESH_AGGREGATOR,
)
from services.appliance_dashboard.mesh_sharding_handler import MeshShardingHandler
from services.appliance_dashboard.model_manager_handler import ModelManagerHandler
from services.appliance_dashboard.system_actions import SystemActionsHandler
from services.appliance_dashboard.telemetry_handler import TelemetryHandler
from services.appliance_dashboard.template_loader import get_dashboard_html
from services.appliance_dashboard.webapp_handler import WebAppsHandler
from tools.appliance.appliance_config import (
    ApplianceConfig,
    load_appliance_config,
)
from tools.appliance.hardware_detector import (
    RigInventory,
    scan_rig_hardware_stable,
)
from tools.appliance.node_identity import (
    read_enrolled_node_id,
    resolve_node_id,
)

log = logging.getLogger("computemesh.appliance.server")
APPLIANCE_VERSION = CONFIG.appliance_version
PORTAL_DIR = (REPO_ROOT / "portal").resolve()
DASHBOARD_SESSION_COOKIE = "cm_dashboard_session"
# Kept for explicit legacy/operator sessions supplied in a header or cookie.
# The dashboard never mints this process-wide value for anonymous visitors.
DASHBOARD_SESSION_TOKEN = secrets.token_urlsafe(32)
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
ALLOWED_CORS_ORIGINS = {
    "https://mesh.inetconnector.com",
    "https://ai.inetconnector.com",
    "https://inetconnector.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}
FAN_SAFETY_CONTROLLER: Any = None


def _mesh_poller_enabled() -> bool:
    return os.environ.get("COMPUTEMESH_AUTOSTART_MESH_POLLER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _is_loopback_port_in_use(candidate_port: int) -> bool:
    """Probes if another process is already listening on 127.0.0.1:candidate_port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.15)
        try:
            probe.connect(("127.0.0.1", candidate_port))
            return True
        except (OSError, socket.timeout):
            return False


def _safe_resolve_portal_file(filename: str) -> Path | None:
    """Canonicalizes and verifies that a target file strictly resides within PORTAL_DIR or PyInstaller MEIPASS."""
    if "\0" in filename or ".." in filename:
        return None
    raw_sub = filename.lstrip("/\\")

    # Clean URL aliases matching Apache/Nginx portal routing
    alias_map = {
        "downloads": "downloads.html",
        "models": "models.html",
        "datenschutz": "privacy.html",
        "kontakt": "contact.html",
    }
    clean_sub = raw_sub.rstrip("/\\")
    sub_path = alias_map.get(clean_sub, raw_sub)

    candidates: list[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "portal" / sub_path)
        candidates.append(Path(sys._MEIPASS) / sub_path)
    candidates.append(PORTAL_DIR / sub_path)
    candidates.append(REPO_ROOT / "portal" / sub_path)

    for c in candidates:
        try:
            resolved = c.resolve()
            # 1. Exact file match
            if resolved.is_file():
                return resolved
            # 2. Directory with index.html
            if (resolved / "index.html").is_file():
                return (resolved / "index.html").resolve()
            # 3. Clean URL without .html extension (e.g. /pricing -> pricing.html)
            html_candidate = resolved.with_suffix(".html")
            if html_candidate.is_file():
                return html_candidate.resolve()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
            log.debug("Candidate path resolution skipped: %s", exc)
            continue
    return None


def get_service_status_payload(server_port: int = 8080) -> dict:
    """Returns the platform daemon/service state (Windows Service or systemd)."""
    installed = False
    status_val = "NOT_INSTALLED"

    if sys.platform == "win32":
        try:
            from tools.appliance.windows_service import query_service_status
            st = query_service_status()
            status_val = st.get("status", "UNKNOWN")
            installed = (st.get("installed") == "true")
        except Exception as e:
            status_val = f"ERROR: {e}"
    else:
        try:
            res = subprocess.run(["systemctl", "is-active", "computemesh-node"], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                status_val = "RUNNING"
                installed = True
            elif res.stdout.strip() in ("inactive", "failed"):
                status_val = "STOPPED"
                installed = True
        except Exception:
            pass

    runner_mode = "service" if status_val == "RUNNING" else "user_process"
    return {
        "platform": sys.platform,
        "service_name": "ComputeMeshNode" if sys.platform == "win32" else "computemesh-node",
        "is_service_installed": installed,
        "service_status": status_val,
        "runner_mode": runner_mode,
        "port": server_port,
    }


def execute_service_control(action: str) -> tuple[bool, str]:
    """Control Windows Service or systemd daemon (start, stop, restart)."""
    action = str(action or "").strip().lower()
    ok = False
    msg = ""
    if sys.platform == "win32":
        from tools.appliance.windows_service import start_service, stop_service
        if action == "start":
            ok = start_service()
            msg = "Service started" if ok else "Failed to start service"
        elif action == "stop":
            ok = stop_service()
            msg = "Service stopped" if ok else "Failed to stop service"
        elif action == "restart":
            stop_service()
            time.sleep(1.0)
            ok = start_service()
            msg = "Service restarted" if ok else "Failed to restart service"
        else:
            msg = f"Unknown action: {action}"
    else:
        if action in ("start", "stop", "restart"):
            res = subprocess.run(["systemctl", action, "computemesh-node"], capture_output=True, text=True, check=False)
            ok = (res.returncode == 0)
            msg = f"systemctl {action} returned {res.returncode}"
        else:
            msg = f"Unknown action: {action}"
    return ok, msg


class DashboardHandler(BaseHTTPRequestHandler):
    """Slim coordinator HTTP request handler delegating to modular sub-handlers."""
    server_version = "ComputeMesh-NodeOS/1.2"
    sys_version = ""

    config: ApplianceConfig
    inventory: RigInventory
    node_id: str
    tokens_served: int = 0
    earnings_cm: float = 0.0
    _qr_rate_lock = threading.Lock()
    _qr_rate_windows: ClassVar[dict[str, list[float]]] = {}

    def _current_node_id(self) -> str:
        enrolled = read_enrolled_node_id()
        if enrolled is not None:
            return enrolled
        configured = str(getattr(self.config, "rig_name", "") or "").strip()
        if configured and not (configured == "test-node-custom" and self.node_id != "test-node-custom"):
            return configured
        return self.node_id

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _verify_admin_auth(self) -> bool:
        supplied_token = self.headers.get("X-Node-Auth-Token", "")
        authorization = self.headers.get("Authorization", "")
        if not supplied_token and authorization.startswith("Bearer "):
            supplied_token = authorization.removeprefix("Bearer ")
        if not supplied_token:
            for item in str(self.headers.get("Cookie", "")).split(";"):
                name, sep, value = item.strip().partition("=")
                if sep and name == DASHBOARD_SESSION_COOKIE:
                    supplied_token = value.strip()
                    break

        return bool(supplied_token and (hmac.compare_digest(supplied_token.strip(), _tunnel_relay.NODE_AUTH_TOKEN.strip()) or hmac.compare_digest(supplied_token.strip(), DASHBOARD_SESSION_TOKEN.strip())))

    def _send_cors_headers(self) -> None:
        """Allow only the known portal origins to call authenticated APIs."""
        origin = str(self.headers.get("Origin", "")).strip()
        if origin in ALLOWED_CORS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _verify_action_auth(self) -> bool:
        return self._verify_admin_auth()

    def _verify_owner_inference_auth(self) -> bool:
        """Allow the paired fleet owner or local loopback client to use inference on this local node.

        The node token remains mandatory for dashboard and administrative
        actions. A configured owner key is a separate, narrowly scoped LAN
        inference grant. Loopback clients (127.0.0.1 / localhost) from the
        local WebUI or tools are authorized while blocking cross-site CSRF.
        """
        client_ip = str(getattr(self, "client_address", ("", 0))[0] or "")
        try:
            ip_obj = ipaddress.ip_address(client_ip)
            if not (ip_obj.is_private or ip_obj.is_loopback):
                return False
        except ValueError:
            return False

        if ip_obj.is_loopback:
            sec_fetch_site = str(self.headers.get("Sec-Fetch-Site", "")).strip().lower()
            if sec_fetch_site == "cross-site":
                return False
            origin = str(self.headers.get("Origin", "")).strip()
            if origin and not (
                origin in ALLOWED_CORS_ORIGINS
                or "127.0.0.1" in origin
                or "localhost" in origin
            ):
                return False
            return True

        configured = getattr(self, "config", None)
        if configured is None:
            configured = getattr(DashboardHandler, "config", None)
        configured_key = str(getattr(configured, "owner_key", "") or "").strip()
        if not configured_key:
            return False
        supplied_key = str(self.headers.get("X-Owner-Key", "") or "").strip()
        if not supplied_key:
            authorization = str(self.headers.get("Authorization", "") or "").strip()
            if authorization.startswith("Bearer "):
                supplied_key = authorization.removeprefix("Bearer ").strip()
        return bool(supplied_key) and hmac.compare_digest(supplied_key, configured_key)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Node-Auth-Token, X-Owner-Key, Accept, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        resp = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _send_unauthorized(self) -> None:
        self._send_json(
            {"error": {"message": "Unauthorized: open the dashboard first or provide a valid node authentication header", "code": 401}},
            HTTPStatus.UNAUTHORIZED,
        )

    def _qr_rate_allowed(self) -> bool:
        """Allow a small number of authenticated QR renders per client."""
        client_ip = str(getattr(self, "client_address", ("unknown", 0))[0] or "unknown")
        now = time.monotonic()
        with self._qr_rate_lock:
            recent = [stamp for stamp in self._qr_rate_windows.get(client_ip, []) if now - stamp < 60.0]
            if len(recent) >= 30:
                self._qr_rate_windows[client_ip] = recent
                return False
            recent.append(now)
            self._qr_rate_windows[client_ip] = recent
            return True

    def _handle_local_qr(self, parsed_url: urllib.parse.ParseResult) -> bool:
        """Render a short-lived dashboard QR without a third-party image host."""
        if not self._verify_admin_auth():
            self._send_unauthorized()
            return True
        if not self._qr_rate_allowed():
            self._send_json(
                {"error": {"message": "QR generation rate limit exceeded", "code": 429}},
                HTTPStatus.TOO_MANY_REQUESTS,
            )
            return True
        query = urllib.parse.parse_qs(parsed_url.query, keep_blank_values=False)
        text = str((query.get("data") or query.get("text") or [""])[0]).strip()
        if not text or len(text) > 2048:
            self._send_json(
                {"error": {"message": "A QR data URL up to 2048 characters is required", "code": 400}},
                HTTPStatus.BAD_REQUEST,
            )
            return True
        target = urllib.parse.urlparse(text)
        if target.scheme not in {"http", "https"} or target.username or target.password:
            self._send_json(
                {"error": {"message": "QR data must be an HTTP(S) URL without credentials", "code": 400}},
                HTTPStatus.BAD_REQUEST,
            )
            return True
        try:
            import qrcode
            import qrcode.image.svg

            image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
            output = io.BytesIO()
            image.save(output)
            payload = output.getvalue()
        except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            log.warning("Local QR generation unavailable: %s", exc)
            self._send_json(
                {"error": {"message": "Local QR generation is unavailable", "code": 503}},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        return True

    def _handle_service_status(self) -> None:
        """Returns the platform daemon/service state (Windows Service or systemd)."""
        server_port = getattr(self.server, "server_port", 8080) if hasattr(self, "server") else 8080
        payload = get_service_status_payload(server_port=server_port)
        self._send_json(payload, HTTPStatus.OK)

    def _handle_service_control(self, post_body: bytes) -> None:
        """Control Windows Service or systemd daemon (start, stop, restart)."""
        try:
            data = json.loads(post_body.decode("utf-8")) if post_body else {}
            action = str(data.get("action", "")).strip().lower()
            ok, msg = execute_service_control(action)
            self._send_json({"success": ok, "message": msg, "action": action}, HTTPStatus.OK if ok else HTTPStatus.BAD_REQUEST)
        except Exception as e:
            self._send_json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path
        client_ip = str(getattr(self, "client_address", ("", 0))[0] or "")
        try:
            is_loopback = ipaddress.ip_address(client_ip).is_loopback
        except ValueError:
            is_loopback = False

        if req_path == "/api/appliance/loopback_token":
            if not is_loopback:
                self._send_unauthorized()
                return
            sec_fetch_site = str(self.headers.get("Sec-Fetch-Site", "")).strip().lower()
            if sec_fetch_site == "cross-site":
                self._send_unauthorized()
                return
            self._send_json({
                "token": _tunnel_relay.NODE_AUTH_TOKEN,
                "session": DASHBOARD_SESSION_TOKEN,
            }, HTTPStatus.OK)
            return

        if MeshShardingHandler.handle_get(self, req_path):
            return

        if ModelManagerHandler.handle_get(self, req_path, parsed_url.query):
            return

        if InferenceRouter.handle_get(self, req_path, APPLIANCE_VERSION):
            return

        if req_path in ("/api/portal/qr", "/api/v1/qr"):
            self._handle_local_qr(parsed_url)
            return

        if req_path == "/api/appliance/service/status":
            self._handle_service_status()
            return

        if FanControlHandler.handle_get(self, req_path):
            return

        if req_path in ("", "/", "/index.html"):
            token_to_inject = _tunnel_relay.NODE_AUTH_TOKEN if is_loopback else None
            html = get_dashboard_html(auth_token=token_to_inject)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._send_cors_headers()
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        # llama.cpp WebUI & Chat Studio static assets
        clean_path = req_path.rstrip("/")
        if clean_path in ("/webui", "/chat", "/llama") or req_path in ("/webui/", "/chat/", "/llama/"):
            index_target = _safe_resolve_portal_file("webui/index.html")
            if index_target and index_target.exists():
                data = index_target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        # Agent Workspace routes
        if clean_path in ("/agent", "/agent.html") or req_path in ("/agent/",):
            agent_target = _safe_resolve_portal_file("agent.html")
            if agent_target and agent_target.exists():
                data = agent_target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if req_path.startswith("/agent-workspace/"):
            sub_rel = req_path.removeprefix("/agent-workspace/").lstrip("/\\")
            target_f = _safe_resolve_portal_file(f"agent-workspace/{sub_rel}")
            if target_f and target_f.exists():
                suffix = target_f.suffix.lower()
                ctype = "application/javascript; charset=utf-8" if suffix in (".js", ".mjs") else "text/css; charset=utf-8" if suffix == ".css" else "application/octet-stream"
                data = target_f.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if req_path.startswith("/webui/"):
            sub_rel = req_path.removeprefix("/webui/")
            target_f = _safe_resolve_portal_file(f"webui/{sub_rel}")
            if target_f and target_f.exists():
                suffix = target_f.suffix.lower()
                content_types = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".mjs": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".webmanifest": "application/manifest+json; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".ico": "image/x-icon",
                    ".wasm": "application/wasm",
                }
                ctype = content_types.get(suffix, "application/octet-stream")
                data = target_f.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if req_path.startswith(("/_app/", "/workbox-")) or req_path in ("/sw.js", "/build.json", "/manifest.webmanifest"):
            sub_rel = req_path.lstrip("/")
            target_f = _safe_resolve_portal_file(f"webui/{sub_rel}")
            if target_f and target_f.exists():
                suffix = target_f.suffix.lower()
                content_types = {
                    ".html": "text/html; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".mjs": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".webmanifest": "application/manifest+json; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".ico": "image/x-icon",
                    ".wasm": "application/wasm",
                }
                ctype = content_types.get(suffix, "application/octet-stream")
                data = target_f.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if req_path.startswith("/generated/"):
            sub_rel = req_path.removeprefix("/generated/").lstrip("/\\")
            target_f = _safe_resolve_portal_file(f"generated/{sub_rel}")
            if target_f and target_f.exists():
                suffix = target_f.suffix.lower()
                ctype = "image/png" if suffix == ".png" else "image/jpeg" if suffix in (".jpg", ".jpeg") else "application/octet-stream"
                data = target_f.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self._send_cors_headers()
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if KillswitchHandler.handle_get(self, req_path):
            return

        if TelemetryHandler.handle_get(self, req_path):
            return

        if SystemActionsHandler.handle_get(self, req_path, APPLIANCE_VERSION):
            return

        if WebAppsHandler.handle_get(self, req_path):
            return

        # General static portal asset resolution (CSS, JS, SVG, images, fonts)
        portal_asset = _safe_resolve_portal_file(req_path)
        if portal_asset and portal_asset.is_file():
            suffix = portal_asset.suffix.lower()
            content_types = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".mjs": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".webmanifest": "application/manifest+json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".ico": "image/x-icon",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".ttf": "font/ttf",
                ".wasm": "application/wasm",
                ".apk": "application/vnd.android.package-archive",
                ".aab": "application/octet-stream",
                ".exe": "application/vnd.microsoft.portable-executable",
                ".iso": "application/x-iso9660-image",
                ".gz": "application/gzip",
                ".xz": "application/x-xz",
                ".zip": "application/zip",
            }
            ctype = content_types.get(suffix, "application/octet-stream")
            data = portal_asset.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self._send_cors_headers()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        req_path = parsed_url.path
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json({"error": {"message": "Invalid Content-Length", "code": "invalid_request_error"}}, HTTPStatus.BAD_REQUEST)
            return
        if content_len < 0:
            self._send_json({"error": {"message": "Invalid Content-Length", "code": "invalid_request_error"}}, HTTPStatus.BAD_REQUEST)
            return
        if content_len > MAX_REQUEST_BODY_BYTES:
            self._send_json({"error": {"message": "Request body is too large", "code": "request_too_large"}}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        # Administrative POST routes require the node token. The paired fleet
        # owner may use only the inference routes with the configured owner
        # key; anonymous LAN callers never reach the agent loop.
        authorized = self._verify_action_auth()
        inference_paths = {
            "/v1/chat/completions",
            "/chat/completions",
            "/completion",
            "/completions",
            "/v1/completions",
            "/complete",
            "/models/load",
            "/models/unload",
            "/props",
            "/slots",
            "/webui/props",
            "/webui/slots",
            "/webui/chat/completions",
            "/webui/completion",
            "/webui/completions",
            "/webui/v1/chat/completions",
            "/webui/v1/completions",
            "/infill",
            "/webui/infill",
            "/api/chat",
            "/api/v1/chat",
            "/api/generate",
            "/api/v1/generate",
        }
        if not authorized and req_path in inference_paths:
            authorized = self._verify_owner_inference_auth()
        if not authorized:
            self._send_unauthorized()
            return

        if req_path == "/api/appliance/service/control":
            self._handle_service_control(post_body)
            return

        if MeshShardingHandler.handle_post(self, req_path, post_body):
            return

        if ModelManagerHandler.handle_post(self, req_path, post_body):
            return

        if InferenceRouter.handle_post(self, req_path, post_body):
            return

        if FanControlHandler.handle_post(self, req_path, post_body):
            return

        if KillswitchHandler.handle_post(self, req_path, post_body):
            return

        if SystemActionsHandler.handle_post(self, req_path, post_body, APPLIANCE_VERSION):
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

    effective_node_id = resolve_node_id(
        fallback_node_id=str(config.rig_name or node_id or "cm-node").strip()
    )
    DashboardHandler.config = config
    DashboardHandler.inventory = inventory
    DashboardHandler.node_id = effective_node_id

    # NodeOS must not rely on zero-RPM driver defaults. The controller is
    # capability-aware and is a no-op on Windows drivers without fan access.
    global FAN_SAFETY_CONTROLLER
    try:
        from tools.appliance.fan_control import FanSafetyController
        FAN_SAFETY_CONTROLLER = FanSafetyController(inventory, config)
        FAN_SAFETY_CONTROLLER.start()
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
        log.warning("Fan safety controller unavailable: %s", exc)

    # The dashboard is a UI/HTTP surface, not a heartbeat owner.  The
    # platform-specific launcher (Windows/Linux tray or the NodeOS systemd
    # heartbeat unit after preflight) owns exactly one relay instance.  Starting
    # one here would race that owner and emit duplicate heartbeats.

    server_inst = None
    actual_port = port
    if port == 0:
        # Port zero is an explicit request for an OS-assigned ephemeral port.
        # Never reinterpret it as the production service-port fallback: test
        # harnesses, embedded callers and parallel local dashboards rely on
        # collision-free allocation.
        server_inst = ReusableThreadingHTTPServer((host, 0), DashboardHandler)
        actual_port = server_inst.server_address[1]
    else:
        candidate_ports: list[int] = []
        for p in [port, 8080, 8081, 8082, 8083, 8084, 8085]:
            if p not in candidate_ports:
                candidate_ports.append(p)

        for candidate_port in candidate_ports:
            # On Windows/Linux with SO_REUSEADDR, binding 0.0.0.0 may succeed even if
            # 127.0.0.1:candidate_port is already held by another app (e.g. tunnel-client).
            # Avoid port shadowing where local requests to localhost hit the other app.
            if _is_loopback_port_in_use(candidate_port):
                continue
            try:
                server_inst = ReusableThreadingHTTPServer((host, candidate_port), DashboardHandler)
                actual_port = server_inst.server_address[1]
                break
            except OSError:
                continue

        if server_inst is None:
            server_inst = ReusableThreadingHTTPServer((host, 0), DashboardHandler)
            actual_port = server_inst.server_address[1]

    try:
        p_file = Path.home() / ".computemesh" / "dashboard_port"
        p_file.parent.mkdir(parents=True, exist_ok=True)
        p_file.write_text(str(actual_port), encoding="utf-8")
    except Exception:
        pass

    try:
        from tools.appliance.lan_discovery_responder import (
            start_lan_discovery_responder,
        )
        gpu_name = inventory.gpus[0].model_name if getattr(inventory, "gpus", None) else "ComputeMesh AI Node"
        start_lan_discovery_responder(node_id=effective_node_id, port=actual_port, gpu_summary=gpu_name)
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
        log.debug("LAN discovery responder start skipped: %s", exc)

    if _mesh_poller_enabled():
        try:
            GLOBAL_MESH_AGGREGATOR.start()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
            log.debug("Mesh aggregator start skipped: %s", exc)

    return server_inst, actual_port


def run_dashboard_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config: ApplianceConfig | None = None,
    inventory: RigInventory | None = None,
    node_id: str = "cm-inference-node-01",
) -> int:
    if _mesh_poller_enabled():
        GLOBAL_MESH_AGGREGATOR.start()
    try:
        from services.appliance_dashboard.tunnel_relay import start_cloud_tunnel_relay

        start_cloud_tunnel_relay(node_id=node_id)
    except Exception as exc:
        log.debug("Tunnel relay start skipped: %s", exc)
    server, actual_port = create_dashboard_server(host, port, config, inventory, node_id)
    try:
        if sys.stdout is not None:
            print(f"ComputeMesh Appliance Dashboard running at http://{host}:{actual_port}")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
        log.debug("Dashboard banner print skipped: %s", exc)

    try:
        server.serve_forever()
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
        log.debug("Dashboard serve_forever exited: %s", exc)
    finally:
        try:
            server.server_close()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
            log.debug("Dashboard server_close error ignored: %s", exc)
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
