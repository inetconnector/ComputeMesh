# SPDX-License-Identifier: Apache-2.0
"""Static Sandboxed WebApp and Game Route Handler for ComputeMesh."""

from __future__ import annotations

from http import HTTPStatus
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any
import urllib.parse

log = logging.getLogger("computemesh.appliance.webapps")

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_DIR = REPO_ROOT / "portal" / "apps"

MIME_EXTENSIONS = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".wasm": "application/wasm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

CSP_HEADER = (
    "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' data: blob:; "
    "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*; "
    "font-src 'self' data: https:;"
)


class WebAppsHandler:
    """Safely serves deployed sandboxed web apps and games under /apps/<app_name>/..."""

    @staticmethod
    def handle_get(handler: Any, req_path: str) -> bool:
        if not req_path.startswith("/apps/") and req_path != "/apps":
            return False

        if req_path in ("/apps", "/apps/"):
            # Redirect to deployed apps JSON index or dashboard
            from services.mcp.builtin.webapp_deployer import list_deployed_webapps
            apps_info = list_deployed_webapps()
            handler._send_json(apps_info)
            return True

        sub_path = req_path[len("/apps/"):].strip("/")
        if not sub_path:
            return False

        parts = sub_path.split("/", 1)
        app_name = parts[0]
        rel_file = parts[1] if len(parts) > 1 else "index.html"
        if not rel_file:
            rel_file = "index.html"

        # Prevent Directory Traversal
        target_app_dir = (APPS_DIR / app_name).resolve()
        APPS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            target_app_dir.relative_to(APPS_DIR.resolve())
        except ValueError:
            handler.send_error(HTTPStatus.FORBIDDEN, "Forbidden: Path Traversal Detected")
            return True

        target_file = (target_app_dir / rel_file).resolve()
        try:
            target_file.relative_to(target_app_dir)
        except ValueError:
            handler.send_error(HTTPStatus.FORBIDDEN, "Forbidden: Path Traversal Detected")
            return True

        if not target_file.exists() or not target_file.is_file():
            handler.send_error(HTTPStatus.NOT_FOUND, f"File not found: {rel_file}")
            return True

        ext = target_file.suffix.lower()
        content_type = MIME_EXTENSIONS.get(ext) or mimetypes.guess_type(str(target_file))[0] or "application/octet-stream"

        try:
            file_data = target_file.read_bytes()
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(file_data)))
            handler.send_header("Content-Security-Policy", CSP_HEADER)
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("X-Frame-Options", "SAMEORIGIN")
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Cache-Control", "no-cache, must-revalidate")
            handler.end_headers()
            handler.wfile.write(file_data)
            return True
        except Exception as exc:
            log.error(f"Error serving static app file {target_file}: {exc}")
            handler.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Error reading file")
            return True
