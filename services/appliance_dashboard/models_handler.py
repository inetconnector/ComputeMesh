"""ComputeMesh Model Management and Lifecycle HTTP Router for Appliance Dashboard."""
from __future__ import annotations

import json
import logging
import urllib.parse
from http import HTTPStatus
from pathlib import Path
from typing import Any

from services.appliance_dashboard.model_engine_service import ModelEngineService
from services.appliance_dashboard.model_manager import ModelManager

log = logging.getLogger("computemesh.appliance.models_handler")


class ModelsHandler:
    """Handles HTTP GET and POST requests for local models and HuggingFace integration."""

    @staticmethod
    def handle_get(handler: Any, req_path: str) -> bool:
        clean_path = req_path.rstrip("/")
        parsed_url = urllib.parse.urlparse(handler.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        manager = ModelManager.get_instance()
        engine = ModelEngineService.get_instance()

        if clean_path in ("/api/models/local", "/api/v1/models/local"):
            models = manager.list_local_models()
            storage = manager.get_storage_stats()
            handler._send_json({
                "storage": storage,
                "models": [
                    {
                        "filename": m.filename,
                        "path": m.path,
                        "size_bytes": m.size_bytes,
                        "size_gb": round(m.size_bytes / (1024**3), 2),
                        "modified_at": m.modified_at,
                        "is_active": m.is_active,
                        "context_length": m.context_length,
                        "layers": m.layers,
                    }
                    for m in models
                ],
            })
            return True

        if clean_path in ("/api/models/huggingface/search", "/api/models/search"):
            q = query_params.get("q", [""])[0]
            results = manager.search_huggingface(q)
            handler._send_json({"results": results, "query": q})
            return True

        if clean_path in ("/api/models/engine/status", "/api/models/status", "/api/v1/models/status"):
            handler._send_json(engine.get_status())
            return True

        if clean_path in ("/api/models/download/progress", "/api/models/downloads"):
            with manager._lock:
                downloads = [
                    {
                        "download_id": d.download_id,
                        "repo_id": d.repo_id,
                        "filename": d.filename,
                        "total_bytes": d.total_bytes,
                        "downloaded_bytes": d.downloaded_bytes,
                        "speed_mb_s": round(d.speed_bytes_per_sec / (1024 * 1024), 2),
                        "percent": d.percent,
                        "status": d.status,
                        "error_message": d.error_message,
                        "started_at": d.started_at,
                        "completed_at": d.completed_at,
                    }
                    for d in manager.active_downloads.values()
                ]
            handler._send_json({"downloads": downloads})
            return True

        return False

    @staticmethod
    def handle_post(handler: Any, req_path: str, post_body: bytes) -> bool:
        clean_path = req_path.rstrip("/")
        if not clean_path.startswith("/api/models/"):
            return False

        # All modification operations require action authentication
        if not handler._verify_action_auth():
            handler._send_unauthorized()
            return True

        manager = ModelManager.get_instance()
        engine = ModelEngineService.get_instance()

        try:
            payload = json.loads(post_body.decode("utf-8")) if post_body else {}
        except Exception:
            payload = {}

        if clean_path in ("/api/models/download", "/api/v1/models/download"):
            url = str(payload.get("url", "")).strip()
            filename = str(payload.get("filename", "")).strip()
            repo_id = str(payload.get("repo_id", "")).strip()
            expected_size = int(payload.get("expected_size_bytes", 0))
            expected_sha = payload.get("expected_sha256")

            if not url or not filename:
                handler._send_json(
                    {"error": {"message": "url and filename are required parameters", "code": 400}},
                    HTTPStatus.BAD_REQUEST,
                )
                return True

            try:
                dl_id = manager.start_download(
                    url=url,
                    filename=filename,
                    repo_id=repo_id,
                    expected_size_bytes=expected_size,
                    expected_sha256=expected_sha,
                )
                handler._send_json({"success": True, "download_id": dl_id, "filename": filename})
            except Exception as exc:
                handler._send_json({"error": {"message": str(exc), "code": 400}}, HTTPStatus.BAD_REQUEST)
            return True

        if clean_path in ("/api/models/download/cancel", "/api/v1/models/download/cancel"):
            dl_id = str(payload.get("download_id", "")).strip()
            ok = manager.cancel_download(dl_id)
            handler._send_json({"success": ok, "download_id": dl_id})
            return True

        if clean_path in ("/api/models/activate", "/api/v1/models/activate"):
            filename = str(payload.get("filename", "")).strip()
            model_id = str(payload.get("model_id", "")).strip() or filename
            ctx_size = payload.get("context_size")
            layers = int(payload.get("layers", 32))

            if not filename:
                handler._send_json(
                    {"error": {"message": "filename or model_path required", "code": 400}},
                    HTTPStatus.BAD_REQUEST,
                )
                return True

            target_path = Path(filename)
            if not target_path.is_absolute():
                target_path = manager.storage_dir / filename

            ok = engine.start_model(
                model_path=str(target_path),
                model_id=model_id,
                context_size=int(ctx_size) if ctx_size else None,
                total_layers=layers,
            )
            status = engine.get_status()
            if ok:
                handler._send_json({"success": True, "status": status})
            else:
                handler._send_json(
                    {"error": {"message": engine.last_error or "Failed to start model engine", "code": 500}, "status": status},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return True

        if clean_path in ("/api/models/deactivate", "/api/v1/models/deactivate"):
            drain_timeout = float(payload.get("drain_timeout", 10.0))
            engine.stop_model(drain_timeout=drain_timeout)
            handler._send_json({"success": True, "status": engine.get_status()})
            return True

        if clean_path in ("/api/models/delete", "/api/v1/models/delete"):
            filename = str(payload.get("filename", "")).strip()
            if not filename:
                handler._send_json(
                    {"error": {"message": "filename is required", "code": 400}},
                    HTTPStatus.BAD_REQUEST,
                )
                return True
            try:
                ok = manager.delete_model(filename)
                handler._send_json({"success": ok, "filename": filename})
            except Exception as exc:
                handler._send_json({"error": {"message": str(exc), "code": 400}}, HTTPStatus.BAD_REQUEST)
            return True

        return False
