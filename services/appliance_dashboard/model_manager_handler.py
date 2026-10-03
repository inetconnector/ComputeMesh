"""Authenticated HTTP routes for local NodeOS model management."""
from __future__ import annotations

from http import HTTPStatus
import json
from typing import Any
import urllib.parse

from services.appliance_dashboard.model_manager import ModelManagerError, get_model_manager


class ModelManagerHandler:
    @staticmethod
    def handles(req_path: str) -> bool:
        return req_path == "/api/models/manage" or req_path.startswith("/api/models/hf/") or req_path.startswith("/api/models/action/")

    @staticmethod
    def handle_get(handler: Any, req_path: str, query: str = "") -> bool:
        if not ModelManagerHandler.handles(req_path):
            return False
        if not handler._verify_admin_auth():
            handler._send_unauthorized()
            return True
        manager = get_model_manager()
        try:
            if req_path == "/api/models/manage":
                handler._send_json(manager.status())
                return True
            if req_path == "/api/models/hf/search":
                params = urllib.parse.parse_qs(query)
                handler._send_json({"results": manager.search_hugging_face(params.get("q", [""])[0])})
                return True
        except ModelManagerError as exc:
            handler._send_json({"error": {"message": str(exc), "code": "model_management_error"}}, HTTPStatus.BAD_REQUEST)
            return True
        return False

    @staticmethod
    def handle_post(handler: Any, req_path: str, post_body: bytes) -> bool:
        if not ModelManagerHandler.handles(req_path):
            return False
        if not handler._verify_admin_auth():
            handler._send_unauthorized()
            return True
        try:
            payload = json.loads(post_body.decode("utf-8")) if post_body else {}
            if not isinstance(payload, dict):
                raise ModelManagerError("request body must be a JSON object")
            manager = get_model_manager()
            if req_path == "/api/models/hf/download":
                result = manager.start_download(
                    model_id=str(payload.get("model_id", "")),
                    repo_id=str(payload.get("repo_id", "")),
                    filename=str(payload.get("filename", "")),
                    revision=str(payload.get("revision", "")),
                    sha256=str(payload.get("sha256", "")),
                    size_bytes=int(payload.get("size_bytes", 0)),
                    layer_count=int(payload.get("layer_count", 0)),
                    quantization=str(payload.get("quantization", "")),
                    license_id=str(payload.get("license_id", "")),
                )
            elif req_path == "/api/models/action/start":
                result = manager.activate(
                    str(payload.get("model_id", "")),
                    context_size=int(payload.get("context_size", 4096)),
                )
            elif req_path == "/api/models/action/stop":
                result = manager.deactivate(str(payload.get("model_id", "")))
            elif req_path == "/api/models/action/delete":
                result = manager.delete(str(payload.get("model_id", "")))
            else:
                return False
            handler._send_json({"status": "ok", "result": result})
            return True
        except (ModelManagerError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            handler._send_json({"error": {"message": str(exc), "code": "model_management_error"}}, HTTPStatus.BAD_REQUEST)
            return True
