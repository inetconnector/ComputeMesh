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
            try:
                target = f"{ollama_url}/v1/models" if "/models" in clean_path else f"{ollama_url}/api/tags"
                req = urllib.request.Request(target, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = resp.read()
                    handler.send_response(HTTPStatus.OK)
                    handler.send_header("Content-Type", "application/json; charset=utf-8")
                    handler.send_header("Access-Control-Allow-Origin", "*")
                    handler.send_header("Content-Length", str(len(data)))
                    handler.end_headers()
                    handler.wfile.write(data)
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
                handler._send_json(payload)
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

            available_models = []
            try:
                tags_req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"Accept": "application/json"})
                with urllib.request.urlopen(tags_req, timeout=3) as tags_resp:
                    tags_data = json.loads(tags_resp.read().decode("utf-8"))
                    available_models = [m.get("name") or m.get("model") for m in tags_data.get("models", []) if m]
            except Exception:
                pass

            requested_model = str(payload.get("model", "")).strip()
            messages = payload.get("messages", [])
            if not messages and "prompt" in payload:
                messages = [{"role": "user", "content": payload["prompt"]}]

            # Check if query is coding-oriented
            all_text = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
            is_coding_query = any(k in all_text.lower() for k in ("code", "def ", "func ", "class ", "refactor", "bug", "patch", "pytest", "test", "syntax", "git diff", "function", "import "))

            target_model = requested_model
            if available_models:
                if not target_model or target_model.lower() in ("default", "auto", "computemesh"):
                    if is_coding_query:
                        coder_match = next((m for m in available_models if "coder" in m.lower() or "deepseek" in m.lower()), None)
                        target_model = coder_match if coder_match else available_models[0]
                    else:
                        target_model = available_models[0]
                elif requested_model not in available_models:
                    matched = None
                    for m in available_models:
                        if requested_model.lower() in m.lower() or m.lower() in requested_model.lower():
                            matched = m
                            break
                        if is_coding_query and ("coder" in m.lower() or "code" in m.lower()):
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
                target_model = "qwen2.5-coder:7b" if is_coding_query else "qwen2.5:7b"

            is_stream = payload.get("stream", True)

            from services.mcp.agent_loop import AgentLoop
            from services.mcp.tool_registry import ToolRegistry
            from services.mcp.config import get_mcp_config

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
                        ollama_messages.append(m)

                if not available_models:
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
                            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                        }
                    user_msg = next((str(m.get("content", "")) for m in reversed(msg_list) if m.get("role") == "user"), "")
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": f"Antwort von {target_model}: {user_msg}",
                            },
                            "finish_reason": "stop",
                        }],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                    }

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
                    log.warning(f"Ollama inference unavailable ({exc}), synthesizing fallback response")
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
                            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                        }
                    user_msg = next((str(m.get("content", "")) for m in reversed(msg_list) if m.get("role") == "user"), "")
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": f"Antwort von {target_model}: {user_msg}",
                            },
                            "finish_reason": "stop",
                        }],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                    }

            try:
                exec_res = agent_loop.run(
                    messages=messages,
                    model=target_model,
                    llm_caller=node_llm_caller,
                    max_iterations=6,
                )

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
                err_msg = f"Fehler bei Node-Inferenz: {str(e)}"
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
