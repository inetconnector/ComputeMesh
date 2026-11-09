"""Inference, Model Discovery, and MCP Agent Routing for ComputeMesh Appliance."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

log = logging.getLogger("computemesh.appliance.inference")


def _managed_runtime_status() -> dict[str, Any] | None:
    try:
        from services.appliance_dashboard.model_manager import get_model_manager
        status = get_model_manager().status()
        engine = status.get("engine", {})
        if engine.get("ready") and engine.get("endpoint") and engine.get("model_id"):
            return status
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
        log.debug("Managed engine status probe skipped: %s", exc)
    try:
        raw_port = os.environ.get("COMPUTEMESH_LLAMA_PORT", "8081")
        req = urllib.request.Request(f"http://127.0.0.1:{raw_port}/health")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            if resp.status == 200:
                mid = ""
                try:
                    m_req = urllib.request.Request(f"http://127.0.0.1:{raw_port}/v1/models")
                    with urllib.request.urlopen(m_req, timeout=0.5) as m_resp:
                        d = json.loads(m_resp.read().decode())
                        if d.get("data"):
                            mid = str(d["data"][0].get("id", "")).strip()
                except Exception:
                    pass
                return {
                    "engine": {
                        "ready": True,
                        "endpoint": f"http://127.0.0.1:{raw_port}",
                        "model_id": mid or "bartowski/qwen2.5-32b-instruct-gguf",
                    },
                    "models": [],
                }
    except Exception:
        pass
    return None


def _find_ollama_binary() -> str | None:
    import shutil
    candidate = shutil.which("ollama")
    if candidate and Path(candidate).is_file():
        return candidate
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        p = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
        if p.is_file():
            return str(p)
    home_p = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    if home_p.is_file():
        return str(home_p)
    return None


def _ensure_ollama_running(timeout: float = 2.5) -> bool:
    raw_ollama = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    ollama_url = raw_ollama if (raw_ollama.startswith(("http://", "https://"))) else f"http://{raw_ollama}"
    try:
        req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            if resp.status == 200:
                return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
        pass

    bin_path = _find_ollama_binary()
    if not bin_path:
        return False

    try:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
        subprocess.Popen([bin_path, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        start_t = time.time()
        while time.time() - start_t < timeout:
            time.sleep(0.3)
            try:
                req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=0.6) as resp:
                    if resp.status == 200:
                        return True
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
                continue
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
        log.debug("Auto-spawn ollama error: %s", exc)
    return False


def _proxy_inference_to_peer(handler: Any, peer: dict[str, Any], payload: dict[str, Any], clean_path: str, is_stream: bool) -> bool:
    endpoint = peer.get("endpoint") or (peer.get("candidate_local_urls", [""])[0] if peer.get("candidate_local_urls") else "")
    if not endpoint:
        return False
    target_url = f"{endpoint.rstrip('/')}{clean_path}"
    body_bytes = json.dumps(payload).encode("utf-8")

    owner_key = ""
    try:
        from tools.appliance.appliance_config import load_appliance_config
        cfg = load_appliance_config()
        owner_key = getattr(cfg, "owner_key", "")
    except Exception:
        pass

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if is_stream else "application/json",
        "User-Agent": "ComputeMesh-FleetProxy/1.2",
    }
    if owner_key:
        headers["X-Owner-Key"] = owner_key

    req = urllib.request.Request(target_url, data=body_bytes, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            handler.send_response(resp.status)
            for h_k, h_v in resp.headers.items():
                if h_k.lower() in ("content-type", "transfer-encoding", "cache-control"):
                    handler.send_header(h_k, h_v)
            handler._send_cors_headers()
            handler.end_headers()

            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
            return True
    except Exception as exc:
        log.warning("Peer offloading to %s failed: %s", target_url, exc)
        return False


def _looks_like_vision_model(model_name: str) -> bool:
    """Return whether an Ollama model name conventionally accepts images."""
    lowered = str(model_name or "").lower()
    return any(token in lowered for token in ("-vl", ":vl", "vision", "llava", "moondream", "gemma3", "gemma4", "minicpm"))


def _ollama_message(message: Any) -> dict[str, Any]:
    """Translate OpenAI multimodal content parts to Ollama's message shape."""
    if not isinstance(message, dict):
        return {"role": "user", "content": str(message)}

    role = str(message.get("role", "user")).strip() or "user"
    content = message.get("content")
    if not isinstance(content, list):
        return {"role": role, "content": str(content or "")}

    text_parts: list[str] = []
    images: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            if part is not None:
                text_parts.append(str(part))
            continue
        part_type = str(part.get("type", "")).lower()
        if part_type == "text":
            text_parts.append(str(part.get("text", "")))
            continue
        if part_type == "image_url":
            image_value = part.get("image_url")
            image_url = image_value.get("url", "") if isinstance(image_value, dict) else image_value
            image_url = str(image_url or "")
            if image_url.startswith("data:image/") and "," in image_url:
                images.append(image_url.split(",", 1)[1])
            elif image_url:
                # Ollama requires base64 image payloads. Do not stringify a
                # remote URL into the prompt; the caller gets a clear error
                # if the selected local model cannot consume it.
                text_parts.append(f"[Bildquelle nicht lokal verfügbar: {image_url}]")

    normalized: dict[str, Any] = {"role": role, "content": "\n".join(text_parts).strip()}
    if images:
        normalized["images"] = images
    return normalized


def _ensure_image_engine_running(timeout: float = 3.0) -> bool:
    """Verifies or auto-launches the local sd-server image engine on port 8085 if available."""
    try:
        req = urllib.request.Request("http://127.0.0.1:8085/v1/models", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
        log.debug("Initial image engine probe skipped: %s", exc)

    # Check if sd-server binary and script exist to auto-spawn
    try:
        repo_root = Path(__file__).resolve().parents[2]
        service_script = repo_root / "runtime" / "sd_cpp" / "image_engine_service.py"
        if service_script.exists():
            subprocess.Popen([sys.executable, str(service_script), "--port", "8085"], cwd=str(repo_root))
            start_t = time.time()
            while time.time() - start_t < timeout:
                try:
                    time.sleep(0.5)
                    req = urllib.request.Request("http://127.0.0.1:8085/v1/models", headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=0.8) as resp:
                        if resp.status == 200:
                            return True
                except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as poll_exc:
                    log.debug("Image engine poll attempt skipped: %s", poll_exc)
                    continue
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
        log.debug(f"Auto-spawn image engine error: {exc}")
    return False


class InferenceRouter:
    """Handles OpenAI/Ollama-compatible endpoints, MCP tool loops, and image generation."""

    @staticmethod
    def handle_get(
        handler: Any,
        req_path: str,
        appliance_version: str,
    ) -> bool:
        raw_ollama = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
        ollama_url = raw_ollama if (raw_ollama.startswith(("http://", "https://"))) else f"http://{raw_ollama}"
        clean_path = req_path.rstrip("/")
        managed = _managed_runtime_status()

        # 1. Models & Tags listing
        if clean_path in ("/v1/models", "/models", "/api/tags", "/tags", "/webui/models", "/webui/v1/models", "/api/models", "/api/v1/models"):
            # If the user in a browser navigates to /models expecting the portal webpage, let DashboardHandler serve models.html
            if clean_path == "/models" and "text/html" in str(handler.headers.get("Accept", "")).lower() and "application/json" not in str(handler.headers.get("Accept", "")).lower():
                return False

            _ensure_ollama_running()
            combined_models: list[dict[str, Any]] = []
            seen_model_ids: set[str] = set()

            # 1. Local managed model
            if managed is not None:
                engine = managed["engine"]
                mid = str(engine.get("model_id", "")).strip()
                if mid:
                    installed = next((item for item in managed.get("models", []) if item.get("model_id") == mid), {})
                    combined_models.append({
                        "id": mid,
                        "name": mid,
                        "model": mid,
                        "size": int(installed.get("size_bytes", 0) or 0),
                        "digest": f"sha256:{installed.get('sha256')}" if installed.get("sha256") else "",
                        "owned_by": "local-managed",
                        "details": {"format": "gguf", "quantization_level": installed.get("quantization", "")},
                    })
                    seen_model_ids.add(mid)

            # 2. Local installed GGUF models in model_manager
            try:
                from services.appliance_dashboard.model_manager import get_model_manager
                installed_mgr = get_model_manager().status().get("models", [])
                for item in installed_mgr:
                    mid = str(item.get("model_id", "")).strip()
                    if mid and mid not in seen_model_ids:
                        combined_models.append({
                            "id": mid,
                            "name": mid,
                            "model": mid,
                            "size": int(item.get("size_bytes", 0) or 0),
                            "digest": f"sha256:{item.get('sha256')}" if item.get("sha256") else "",
                            "owned_by": "local",
                            "details": {"format": "gguf", "quantization_level": item.get("quantization", "")},
                        })
                        seen_model_ids.add(mid)
            except Exception as exc:
                log.debug("Installed model scan error: %s", exc)

            # 3. Local Ollama models
            try:
                req_ol = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
                with urllib.request.urlopen(req_ol, timeout=2.5) as resp_ol:
                    if resp_ol.status == 200:
                        ol_data = json.loads(resp_ol.read().decode("utf-8"))
                        for item in ol_data.get("models", []):
                            mid = str(item.get("name") or item.get("model") or "").strip()
                            if mid and mid not in seen_model_ids:
                                combined_models.append({
                                    "id": mid,
                                    "name": mid,
                                    "model": mid,
                                    "size": int(item.get("size", 0) or 0),
                                    "digest": str(item.get("digest", "")),
                                    "owned_by": "local-ollama",
                                    "details": item.get("details", {}),
                                })
                                seen_model_ids.add(mid)
            except Exception:
                pass

            # 4. Fleet Peer Models from cluster
            try:
                from services.appliance_dashboard.mesh_aggregator import GLOBAL_MESH_AGGREGATOR
                for peer in GLOBAL_MESH_AGGREGATOR.get_online_peers():
                    peer_nid = peer.get("node_id", "peer")
                    active_p = str(peer.get("active_model", "")).strip()
                    if active_p and active_p not in seen_model_ids:
                        combined_models.append({
                            "id": active_p,
                            "name": active_p,
                            "model": active_p,
                            "size": 0,
                            "digest": "",
                            "owned_by": f"fleet-peer:{peer_nid}",
                            "details": {"format": "gguf", "fleet_peer": peer_nid},
                        })
                        seen_model_ids.add(active_p)
                    for pm in peer.get("models", []):
                        pm_id = str(pm.get("model_id") if isinstance(pm, dict) else pm).strip()
                        if pm_id and pm_id not in seen_model_ids:
                            combined_models.append({
                                "id": pm_id,
                                "name": pm_id,
                                "model": pm_id,
                                "size": int(pm.get("size_bytes", 0) or 0) if isinstance(pm, dict) else 0,
                                "digest": f"sha256:{pm.get('sha256')}" if (isinstance(pm, dict) and pm.get("sha256")) else "",
                                "owned_by": f"fleet-peer:{peer_nid}",
                                "details": {"format": "gguf", "fleet_peer": peer_nid},
                            })
                            seen_model_ids.add(pm_id)
            except Exception as exc:
                log.debug("Peer model enumeration skipped: %s", exc)

            if clean_path in ("/api/tags", "/tags"):
                handler._send_json({"models": [{
                    "name": m["name"],
                    "model": m["model"],
                    "size": m.get("size", 0),
                    "digest": m.get("digest", ""),
                    "details": m.get("details", {}),
                } for m in combined_models]})
            else:
                models_data = [{
                    "id": m["id"],
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": m.get("owned_by", "local"),
                    "permission": [],
                    "root": m["id"],
                    "parent": None,
                } for m in combined_models]
                handler._send_json({"object": "list", "data": models_data})
            return True

        if clean_path in ("/props", "/webui/props", "/api/props", "/v1/props", "/slots", "/webui/slots", "/api/slots", "/v1/slots", "/tools", "/webui/tools", "/api/tools", "/v1/tools", "/api/version", "/version"):
            # Discover active local model
            active_model = ""
            if managed is not None:
                active_model = managed["engine"]["model_id"]
            if not active_model:
                try:
                    req_tags = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req_tags, timeout=0.8) as resp_tags:
                        tdata = json.loads(resp_tags.read().decode("utf-8"))
                        m_list = tdata.get("models", [])
                        if m_list:
                            active_model = m_list[0].get("name") or m_list[0].get("model") or ""
                except Exception:
                    pass
            if not active_model:
                active_model = "qwen2.5:3b"

            if clean_path in ("/props", "/webui/props", "/api/props", "/v1/props"):
                handler._send_json({
                    "default_generation_settings": {
                        "n_predict": 2048,
                        "temperature": 0.7,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                        "n_ctx": 32768,
                        "model": active_model,
                    },
                    "total_slots": 1,
                    "model_path": active_model,
                    "model_alias": active_model,
                    "build_info": f"ComputeMesh Node Engine v{appliance_version} (Local CUDA)",
                    "modalities": {"vision": False, "audio": False, "video": False},
                    "webui_settings": {
                        "theme": "Dark",
                        "system_message": "Du bist ComputeMesh AI, ein hochperformanter intelligenter Assistent im dezentralen GPU-Netzwerk mit Live-Werkzeugen.",
                    },
                })
            elif clean_path in ("/slots", "/webui/slots", "/api/slots", "/v1/slots"):
                handler._send_json([{"id": 0, "is_processing": False, "model": active_model}])
            elif clean_path in ("/api/version", "/version"):
                handler._send_json({"version": appliance_version})
            else:
                handler._send_json([])
            return True

        return False

    @staticmethod
    def handle_post(
        handler: Any,
        req_path: str,
        post_body: bytes,
    ) -> bool:
        clean_path = req_path.rstrip("/")
        raw_ollama = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
        ollama_url = raw_ollama if (raw_ollama.startswith(("http://", "https://"))) else f"http://{raw_ollama}"
        managed = _managed_runtime_status()

        # 0. Lifecycle & Props
        if clean_path in ("/models/load", "/models/unload", "/webui/models/load", "/webui/models/unload"):
            handler._send_json({"success": True})
            return True

        if clean_path in ("/props", "/webui/props", "/api/props", "/v1/props", "/slots", "/webui/slots", "/api/slots", "/v1/slots"):
            return InferenceRouter.handle_get(handler, req_path, "1.2.206")

        # 1. Chat completions & Generation with autonomous MCP Tool Execution Loop
        if clean_path in (
            "/v1/chat/completions",
            "/chat/completions",
            "/completions",
            "/completion",
            "/complete",
            "/v1/completions",
            "/api/chat",
            "/api/generate",
            "/webui/chat/completions",
            "/webui/v1/chat/completions",
            "/webui/completion",
            "/webui/completions",
            "/webui/v1/completions",
            "/infill",
            "/webui/infill",
        ):
            try:
                from runtime.safety.dead_mans_switch import get_lease_guard
                guard = get_lease_guard(handler._current_node_id())
                if guard.is_tripped:
                    handler._send_json(
                        {"error": {"message": f"Execution blocked: Emergency Kill Switch is tripped ({guard.trip_reason})", "code": 503}},
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return True
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
                log.debug("Kill-switch guard check skipped: %s", exc)

            try:
                payload = json.loads(post_body.decode("utf-8")) if post_body else {}
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
                payload = {}

            local_models = []
            if managed is not None:
                eng_mid = managed.get("engine", {}).get("model_id")
                if eng_mid:
                    local_models.append(eng_mid)
                for m in managed.get("models", []):
                    mid = m.get("model_id") if isinstance(m, dict) else str(m)
                    if mid and mid not in local_models:
                        local_models.append(mid)
            if not local_models:
                _ensure_ollama_running()
                try:
                    tags_req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
                    with urllib.request.urlopen(tags_req, timeout=3) as tags_resp:
                        tags_data = json.loads(tags_resp.read().decode("utf-8"))
                        local_models = [m.get("name") or m.get("model") for m in tags_data.get("models", []) if m]
                except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
                    log.debug("Local Ollama tags probe skipped: %s", exc)

            available_models = list(local_models)
            peer_models: dict[str, dict[str, Any]] = {}
            try:
                from services.appliance_dashboard.mesh_aggregator import GLOBAL_MESH_AGGREGATOR
                for peer in GLOBAL_MESH_AGGREGATOR.get_online_peers():
                    active_p = str(peer.get("active_model", "")).strip()
                    if active_p:
                        peer_models[active_p] = peer
                        if active_p not in available_models:
                            available_models.append(active_p)
                    for pm in peer.get("models", []):
                        pm_id = str(pm.get("model_id") if isinstance(pm, dict) else pm).strip()
                        if pm_id:
                            peer_models[pm_id] = peer
                            if pm_id not in available_models:
                                available_models.append(pm_id)
            except Exception:
                pass

            requested_model = str(payload.get("model", "")).strip()
            messages = payload.get("messages", [])
            if not messages and "prompt" in payload:
                messages = [{"role": "user", "content": payload["prompt"]}]

            # Check if query is coding-oriented
            all_text = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
            is_coding_query = any(k in all_text.lower() for k in ("code", "def ", "func ", "class ", "refactor", "bug", "patch", "pytest", "test", "syntax", "git diff", "function", "import "))
            has_image_input = any(
                isinstance(message, dict)
                and isinstance(message.get("content"), list)
                and any(isinstance(part, dict) and str(part.get("type", "")).lower() == "image_url" for part in message["content"])
                for message in messages
            )

            target_model = requested_model
            if available_models:
                if not target_model or target_model.lower() in ("default", "auto", "computemesh"):
                    if is_coding_query:
                        coder_match = next((m for m in available_models if "coder" in m.lower() or "deepseek" in m.lower()), None)
                        target_model = coder_match if coder_match else available_models[0]
                    else:
                        target_model = available_models[0]
                elif requested_model not in available_models:
                    handler._send_json(
                        {
                            "error": {
                                "message": f"Requested model is not available on this node or connected fleet peers: {requested_model}",
                                "type": "invalid_request_error",
                                "code": "model_not_available",
                                "available_models": available_models,
                            }
                        },
                        HTTPStatus.BAD_REQUEST,
                    )
                    return True
            elif requested_model and requested_model.lower() not in ("default", "auto", "computemesh"):
                handler._send_json(
                    {
                        "error": {
                            "message": "The node model catalogue is unavailable; explicit model selection is refused",
                            "type": "server_error",
                            "code": "model_catalog_unavailable",
                        }
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return True
            if not available_models:
                handler._send_json(
                    {
                        "error": {
                            "message": "No healthy local model runtime or fleet peer is available",
                            "type": "service_unavailable",
                            "code": "model_runtime_unavailable",
                        }
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return True
            if not target_model:
                target_model = "qwen2.5-coder:7b" if is_coding_query else "qwen2.5:7b"

            is_stream = payload.get("stream", True)

            # Check if execution should be offloaded to an online fleet peer
            if target_model in peer_models and target_model not in local_models:
                target_peer = peer_models[target_model]
                if _proxy_inference_to_peer(handler, target_peer, payload, clean_path, is_stream):
                    return True
            elif not local_models and peer_models:
                target_peer = peer_models.get(target_model) or next(iter(peer_models.values()))
                if _proxy_inference_to_peer(handler, target_peer, payload, clean_path, is_stream):
                    return True

            if has_image_input and not _looks_like_vision_model(target_model):
                vision_models = [model for model in available_models if _looks_like_vision_model(model)]
                handler._send_json(
                    {
                        "error": {
                            "message": f"Das ausgewählte Modell {target_model} unterstützt keine Bilder. Bitte wähle ein Vision-Modell.",
                            "type": "invalid_request_error",
                            "code": "vision_model_required",
                            "available_vision_models": vision_models,
                        }
                    },
                    HTTPStatus.BAD_REQUEST,
                )
                return True

            is_stream = payload.get("stream", True)

            from services.mcp.agent_loop import AgentLoop
            from services.mcp.config import get_mcp_config
            from services.mcp.tool_registry import ToolRegistry

            agent_loop = AgentLoop(registry=ToolRegistry(get_mcp_config()))

            def node_llm_caller(msg_list: list[dict[str, Any]], tools_list: list[dict[str, Any]]) -> dict[str, Any]:
                ollama_messages: list[dict[str, Any]] = []
                for m in msg_list:
                    if not isinstance(m, dict):
                        continue
                    r = str(m.get("role", "user")).strip()
                    c = m.get("content")
                    tc = m.get("tool_calls")
                    t_name = m.get("name")
                    if r == "tool":
                        tool_label = f"[MCP Live-Tool Ergebnis ({t_name or 'Werkzeug'})]"
                        formatted_c = str(c or "")
                        ollama_messages.append({
                            "role": "user",
                            "content": f"{tool_label}:\n{formatted_c}\n\nBitte antworte dem Benutzer präzise auf Basis dieses aktuellen Tool-Ergebnisses.",
                        })
                    elif r == "assistant" and tc and not c:
                        call_names = ", ".join(f"{c_item.get('function', {}).get('name', 'tool')}({c_item.get('function', {}).get('arguments', '')})" for c_item in tc if isinstance(c_item, dict))
                        ollama_messages.append({
                            "role": "assistant",
                            "content": f"[Tool aufgerufen: {call_names}]",
                        })
                    else:
                        ollama_messages.append(_ollama_message(m))

                if managed is not None:
                    openai_req: dict[str, Any] = {
                        "model": target_model,
                        "messages": ollama_messages,
                        "stream": False,
                        "temperature": float(payload.get("temperature", 0.7) or 0.7),
                        "max_tokens": min(512, int(payload.get("max_tokens", 512) or 512)),
                    }
                    if tools_list and ("tools" in payload or payload.get("enable_tools")):
                        openai_req["tools"] = tools_list
                    req = urllib.request.Request(
                        f"{managed['engine']['endpoint']}/v1/chat/completions",
                        data=json.dumps(openai_req).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=120) as resp:
                            result = json.loads(resp.read().decode("utf-8"))
                        if not isinstance(result, dict) or not isinstance(result.get("choices"), list):
                            raise TypeError("invalid llama-server response")
                        return result
                    except Exception as exc:
                        log.warning("Managed llama-server inference unavailable: %s", exc)
                        raise RuntimeError("managed model runtime became unavailable") from exc

                ollama_req = {
                    "model": target_model,
                    "messages": ollama_messages,
                    "stream": False,
                    "options": {
                        "temperature": float(payload.get("temperature", 0.7) or 0.7),
                        "num_predict": min(512, int(payload.get("max_tokens", 512) or 512)),
                    },
                }
                try:
                    req = urllib.request.Request(
                        f"{ollama_url}/api/chat",
                        data=json.dumps(ollama_req).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        resp_data = json.loads(resp.read().decode("utf-8"))
                        msg_obj = resp_data.get("message", {})
                        p_tok = resp_data.get("prompt_eval_count", 0)
                        c_tok = resp_data.get("eval_count", 0)
                        return {
                            "choices": [{
                                "message": {
                                    "role": msg_obj.get("role", "assistant"),
                                    "content": msg_obj.get("content", ""),
                                },
                                "finish_reason": "stop",
                            }],
                            "usage": {"prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": p_tok + c_tok},
                        }
                except Exception as exc:
                    log.warning("Ollama inference unavailable: %s", exc)
                    raise RuntimeError("local model runtime became unavailable") from exc

            try:
                exec_res = agent_loop.run(
                    messages=messages,
                    model=target_model,
                    llm_caller=node_llm_caller,
                    # NodeOS requests are provider/runtime requests, not
                    # verified owner sessions. Keep owner-only tools hidden.
                    is_owner=False,
                    max_iterations=6,
                )

                try:
                    from tools.appliance.token_metering import record_tokens
                    stats = record_tokens(
                        prompt_tokens=exec_res.prompt_tokens,
                        completion_tokens=exec_res.completion_tokens,
                    )
                    handler.tokens_served = stats.total_tokens_served
                    handler.earnings_cm = stats.earnings_cm
                except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
                    log.debug("Local token stats update skipped: %s", exc)

                if is_stream:
                    handler.send_response(HTTPStatus.OK)
                    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    handler.send_header("Cache-Control", "no-cache")
                    handler.send_header("Connection", "close")
                    handler._send_cors_headers()
                    handler.end_headers()

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
                    handler.wfile.write(sse_out.encode("utf-8"))
                    handler.wfile.flush()
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
                    handler._send_json(openai_resp)
                return True
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as e:
                err_msg = f"Fehler bei Node-Inferenz: {e!s}"
                handler._send_json({"error": {"message": err_msg, "code": 502}}, HTTPStatus.BAD_GATEWAY)
                return True

        # 2. Image Generation Route (/v1/images/generations)
        if clean_path in (
            "/v1/images/generations",
            "/images/generations",
            "/api/v1/images/generations",
            "/webui/images/generations",
            "/webui/v1/images/generations",
        ):
            try:
                payload = json.loads(post_body.decode("utf-8")) if post_body else {}
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
                payload = {}

            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                handler._send_json({"error": {"message": "Prompt is required", "type": "invalid_request_error"}}, HTTPStatus.BAD_REQUEST)
                return True

            _ensure_image_engine_running(timeout=1.5)

            # Try local CUDA/ROCm sd-server on port 8085
            local_image_url = "http://127.0.0.1:8085/v1/images/generations"
            f_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            f_req = urllib.request.Request(
                local_image_url,
                data=f_bytes,
                headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(f_req, timeout=60.0) as img_resp:
                    img_data = json.loads(img_resp.read().decode("utf-8"))
                    if isinstance(img_data, dict) and "data" in img_data and isinstance(img_data["data"], list):
                        for item in img_data["data"]:
                            if isinstance(item, dict) and "b64_json" in item and not item.get("url"):
                                b64 = item["b64_json"]
                                try:
                                    import base64
                                    import uuid
                                    raw_bytes = base64.b64decode(b64)
                                    img_id = uuid.uuid4().hex[:12]
                                    fname = f"image_{img_id}.png"
                                    gen_dir = REPO_ROOT / "portal" / "generated"
                                    gen_dir.mkdir(parents=True, exist_ok=True)
                                    (gen_dir / fname).write_bytes(raw_bytes)
                                    host_hdr = str(handler.headers.get("Host", "") or "").strip()
                                    scheme = "https" if getattr(getattr(handler, "server", None), "is_tls", False) else "http"
                                    item["url"] = f"{scheme}://{host_hdr}/generated/{fname}" if host_hdr else f"/generated/{fname}"
                                except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError):
                                    item["url"] = f"data:image/png;base64,{b64}"
                    handler._send_json(img_data)
                    return True
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
                log.debug("Local image engine request fell back: %s", exc)

            # Fallback to generate_ai_image tool
            try:
                from services.mcp.builtin.generate_image import generate_ai_image
                res = generate_ai_image(prompt=prompt)
                img_url = res.get("image_url", "")
                handler._send_json({
                    "created": int(time.time()),
                    "data": [{"url": img_url, "revised_prompt": prompt}]
                })
                return True
            except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError) as exc:
                handler._send_json({"error": {"message": f"Image generation error: {exc}", "type": "server_error"}}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return True

        return False
