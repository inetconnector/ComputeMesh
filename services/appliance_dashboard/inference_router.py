"""Inference, Model Discovery, and MCP Agent Routing for ComputeMesh Appliance."""
from __future__ import annotations

from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.parse
import urllib.request

log = logging.getLogger("computemesh.appliance.inference")


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
    except Exception:
        pass

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
                except Exception:
                    continue
    except Exception as exc:
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
        ollama_url = raw_ollama if (raw_ollama.startswith("http://") or raw_ollama.startswith("https://")) else f"http://{raw_ollama}"
        clean_path = req_path.rstrip("/")

        # 1. Models & Tags listing
        if clean_path in ("/v1/models", "/models", "/api/tags", "/tags", "/webui/models", "/webui/v1/models", "/api/models", "/api/v1/models"):
            models_list: list[dict[str, Any]] = []

            # Check local ModelEngineService
            try:
                from services.appliance_dashboard.model_engine_service import ModelEngineService, EngineState
                engine = ModelEngineService.get_instance()
                if engine.state == EngineState.READY and engine.active_model_id:
                    models_list.append({"id": engine.active_model_id, "object": "model", "owned_by": "nodeos-multi-gpu", "active": True})
            except Exception:
                pass

            # Check local ModelManager
            try:
                from services.appliance_dashboard.model_manager import ModelManager
                manager = ModelManager.get_instance()
                for lm in manager.list_local_models():
                    if not any(m["id"] == lm.filename for m in models_list):
                        models_list.append({"id": lm.filename, "object": "model", "owned_by": "local-storage", "size_bytes": lm.size_bytes})
            except Exception:
                pass

            # Check Ollama
            try:
                target = f"{ollama_url}/v1/models" if "/models" in clean_path else f"{ollama_url}/api/tags"
                req = urllib.request.Request(target, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    raw_data = json.loads(resp.read().decode("utf-8"))
                    ollama_items = raw_data.get("data", []) if "data" in raw_data else raw_data.get("models", [])
                    for item in ollama_items:
                        m_id = item.get("id") or item.get("name") or item.get("model")
                        if m_id and not any(m["id"] == m_id for m in models_list):
                            models_list.append({"id": m_id, "object": "model", "owned_by": "ollama"})
            except Exception:
                pass

            if not models_list:
                models_list = [
                    {"id": "gemma3:4b", "object": "model", "owned_by": "computemesh"},
                    {"id": "qwen2.5-coder:14b", "object": "model", "owned_by": "computemesh"},
                    {"id": "qwen2.5:7b", "object": "model", "owned_by": "computemesh"}
                ]

            if "/tags" in clean_path:
                handler._send_json({"models": [{"name": m["id"], "model": m["id"]} for m in models_list]})
            else:
                handler._send_json({"object": "list", "data": models_list})
            return True

        if clean_path in ("/props", "/webui/props", "/api/props", "/v1/props", "/slots", "/webui/slots", "/api/slots", "/v1/slots", "/tools", "/webui/tools", "/api/tools", "/v1/tools", "/api/version", "/version"):
            if clean_path in ("/props", "/webui/props", "/api/props", "/v1/props"):
                handler._send_json({
                    "default_generation_settings": {
                        "n_predict": 2048,
                        "temperature": 0.7,
                        "stop": ["<|im_end|>", "<|endoftext|>"],
                    },
                    "total_slots": 1,
                    "webui_settings": {
                        "theme": "Dark",
                        "system_message": "Du bist ComputeMesh AI, ein hochperformanter intelligenter Assistent im dezentralen GPU-Netzwerk mit Live-Werkzeugen.",
                    },
                })
            elif clean_path in ("/slots", "/webui/slots", "/api/slots", "/v1/slots"):
                handler._send_json([{"id": 0, "is_processing": False}])
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
        ollama_url = raw_ollama if (raw_ollama.startswith("http://") or raw_ollama.startswith("https://")) else f"http://{raw_ollama}"

        # 1. Chat completions & Generation with autonomous MCP Tool Execution Loop
        if clean_path in (
            "/v1/chat/completions",
            "/chat/completions",
            "/completions",
            "/api/chat",
            "/api/generate",
            "/webui/chat/completions",
            "/webui/v1/chat/completions",
            "/webui/completion",
            "/webui/completions",
            "/webui/v1/completions",
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
            except Exception:
                pass

            try:
                payload = json.loads(post_body.decode("utf-8")) if post_body else {}
            except Exception:
                payload = {}

            available_models: list[str] = []

            # Check local ModelEngineService
            try:
                from services.appliance_dashboard.model_engine_service import ModelEngineService, EngineState
                engine = ModelEngineService.get_instance()
                if engine.state == EngineState.READY and engine.active_model_id:
                    available_models.append(engine.active_model_id)
            except Exception:
                pass

            # Check local ModelManager
            try:
                from services.appliance_dashboard.model_manager import ModelManager
                manager = ModelManager.get_instance()
                for lm in manager.list_local_models():
                    if lm.filename not in available_models:
                        available_models.append(lm.filename)
            except Exception:
                pass

            # Check Ollama
            try:
                tags_req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
                with urllib.request.urlopen(tags_req, timeout=2) as tags_resp:
                    tags_data = json.loads(tags_resp.read().decode("utf-8"))
                    for m in tags_data.get("models", []):
                        m_name = m.get("name") or m.get("model")
                        if m_name and m_name not in available_models:
                            available_models.append(m_name)
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
                elif requested_model not in available_models and not any(requested_model.lower() in m.lower() for m in available_models):
                    from services.mcp.intent.intent_router import detect_direct_tool_intent, is_compound_multi_step_query
                    if not (detect_direct_tool_intent(all_text) or is_compound_multi_step_query(all_text)):
                        # An explicit model request is a contract when not handled by autonomous live tools.
                        handler._send_json(
                            {
                                "error": {
                                    "message": f"Requested model is not available on this node: {requested_model}",
                                    "type": "invalid_request_error",
                                    "code": "model_not_available",
                                    "available_models": available_models,
                                }
                            },
                            HTTPStatus.BAD_REQUEST,
                        )
                        return True
            else:
                if not target_model or target_model.lower() in ("default", "auto", "computemesh"):
                    target_model = "qwen2.5-coder:7b" if is_coding_query else "qwen2.5:7b"

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
            from services.mcp.tool_registry import ToolRegistry
            from services.mcp.config import get_mcp_config

            agent_loop = AgentLoop(registry=ToolRegistry(get_mcp_config()))

            def node_llm_caller(msg_list: list[dict[str, Any]], tools_list: list[dict[str, Any]]) -> dict[str, Any]:
                # 1. Check if llama-server ModelEngineService is running with matching model
                try:
                    from services.appliance_dashboard.model_engine_service import ModelEngineService, EngineState
                    engine = ModelEngineService.get_instance()
                    active_id = engine.active_model_id or ""
                    active_fname = Path(engine.active_model_path or "").name

                    is_engine_match = (
                        engine.state == EngineState.READY and
                        (target_model in (active_id, active_fname, "auto", "default", "computemesh") or
                         target_model.replace(".gguf", "") == active_id.replace(".gguf", ""))
                    )

                    if is_engine_match:
                        llama_url = f"http://{engine.config.host}:{engine.config.port}/v1/chat/completions"
                        llama_req = {
                            "model": target_model,
                            "messages": msg_list,
                            "stream": False,
                            "temperature": float(payload.get("temperature", 0.7) or 0.7),
                            "max_tokens": min(2048, int(payload.get("max_tokens", 512) or 512)),
                        }
                        req = urllib.request.Request(
                            llama_url,
                            data=json.dumps(llama_req).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            if resp.status == 200:
                                return json.loads(resp.read().decode("utf-8"))
                except Exception as exc:
                    log.debug(f"Direct llama-server invocation failed: {exc}")

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

                # 2. Try Ollama backend
                try:
                    ollama_req = {
                        "model": target_model,
                        "messages": ollama_messages,
                        "stream": False,
                        "options": {
                            "temperature": float(payload.get("temperature", 0.7) or 0.7),
                            "num_predict": min(512, int(payload.get("max_tokens", 512) or 512)),
                        },
                    }
                    req = urllib.request.Request(
                        f"{ollama_url}/api/chat",
                        data=json.dumps(ollama_req).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            msg = data.get("message", {})
                            return {
                                "choices": [{
                                    "message": {
                                        "role": "assistant",
                                        "content": msg.get("content", ""),
                                    },
                                    "finish_reason": "stop",
                                }],
                                "usage": {
                                    "prompt_tokens": data.get("prompt_eval_count", 0),
                                    "completion_tokens": data.get("eval_count", 0),
                                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                                },
                            }
                except Exception as exc:
                    log.warning(f"Ollama inference unavailable ({exc})")

                # If tool message is present and needs final formatting without active LLM:
                tool_msg = next((m for m in reversed(msg_list) if m.get("role") == "tool"), None)
                if tool_msg:
                    from services.mcp.agent_loop import format_tool_content_if_json
                    formatted = format_tool_content_if_json(str(tool_msg.get("content", "")))
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": formatted,
                            },
                            "finish_reason": "stop",
                        }],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    }

                # Backend is unreachable and model cannot be served: fail cleanly without fake tokens or fake answers
                raise RuntimeError(f"Backend inference engine unavailable for model '{target_model}'.")

            try:
                exec_res = agent_loop.run(
                    messages=messages,
                    model=target_model,
                    llm_caller=node_llm_caller,
                    max_iterations=6,
                )

                # Record metering only when real tokens were generated
                if exec_res.total_tokens > 0:
                    try:
                        handler.tokens_served += int(exec_res.total_tokens)
                        handler.earnings_cm += (exec_res.total_tokens * 0.0001)
                        from tools.appliance.token_metering import record_inference_tokens
                        record_inference_tokens(
                            prompt_tokens=exec_res.prompt_tokens,
                            completion_tokens=exec_res.completion_tokens,
                            model=target_model,
                        )
                    except Exception:
                        pass

                if is_stream:
                    handler.send_response(HTTPStatus.OK)
                    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    handler.send_header("Cache-Control", "no-cache")
                    handler.send_header("Connection", "close")
                    handler.send_header("Access-Control-Allow-Origin", "*")
                    handler.send_header("Access-Control-Allow-Private-Network", "true")
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
            except Exception as e:
                err_msg = f"Inference backend unavailable: {str(e)}"
                log.error(err_msg)
                handler._send_json({"error": {"message": err_msg, "code": 502, "type": "backend_unavailable"}}, HTTPStatus.BAD_GATEWAY)
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
            except Exception:
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
                                    item["url"] = f"/generated/{fname}"
                                except Exception:
                                    item["url"] = f"data:image/png;base64,{b64}"
                    handler._send_json(img_data)
                    return True
            except Exception:
                pass

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
            except Exception as exc:
                handler._send_json({"error": {"message": f"Image generation error: {exc}", "type": "server_error"}}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return True

        return False
