"""ComputeMesh Distributed Inference Engine.

Handles OpenAI-compatible and Ollama-compatible request execution, metering,
and multi-format streaming generation.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import InsufficientBalanceError, Ledger
from services.common.config import CONFIG
from services.common.secure_memory import SecureMemoryBuffer, secure_zero_memory
from services.common.vision_preprocessor import get_vision_preprocessor
from services.gateway.blind_inference import BlindedPipelineEngine
from services.gateway.catalog import (
    AVAILABLE_MODELS,
    DEFAULT_PRICE_TIERS,
    calculate_max_charge_micro,
    calculate_token_charge_micro,
    provider_shares_from_env,
    resolve_model_id,
)
from services.gateway.inference_backend import (
    InferenceBackend,
    InferenceBackendError,
    build_inference_backend_from_env,
)
from services.gateway.metrics_exporter import MetricsRegistry
from services.gateway.security import sanitize_error_message
from services.gateway.teaser import TeaserQuotaManager
from services.mcp.agent_loop import AgentLoop
from services.mcp.config import get_mcp_config
from services.mcp.tool_registry import ToolRegistry

_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _extract_client_tool_calls(
    completion_text: str,
    client_tools: list[dict[str, Any]] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Convert backend tool-call markers into the OpenAI response contract."""
    if not client_tools:
        return completion_text, []
    allowed = {
        str(tool.get("function", {}).get("name", ""))
        for tool in client_tools
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
    }
    calls: list[dict[str, Any]] = []
    decoded_values: list[dict[str, Any]] = []
    matches = list(_TOOL_CALL_PATTERN.finditer(completion_text))
    for match in matches:
        try:
            value = json.loads(match.group(1))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            decoded_values.append(value)
    if not decoded_values:
        raw = completion_text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            raw = fenced.group(1).strip()
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, dict):
            decoded_values = [decoded]
        elif isinstance(decoded, list):
            decoded_values = [value for value in decoded if isinstance(value, dict)]

    for index, value in enumerate(decoded_values):
        function = value.get("function", value) if isinstance(value, dict) else {}
        name = str(function.get("name", "")) if isinstance(function, dict) else ""
        if not name or name not in allowed:
            continue
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        calls.append({
            "id": str(value.get("id") or f"call_computemesh_{index + 1}"),
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments if isinstance(arguments, dict) else {}, ensure_ascii=False),
            },
        })
    content = _TOOL_CALL_PATTERN.sub("", completion_text).strip() if matches else completion_text
    if calls and not matches and decoded_values:
        content = ""
    return content, calls


class InferenceEngine:
    """Executes metered inference, performs quota tracking, and formats responses."""

    def __init__(
        self,
        ledger: Ledger,
        metrics: MetricsRegistry,
        teaser_manager: TeaserQuotaManager,
        backend: InferenceBackend | None = None,
    ) -> None:
        self.ledger = ledger
        self.metrics = metrics
        self.teaser_manager = teaser_manager
        self.backend = backend if backend is not None else build_inference_backend_from_env()
        self.blind_engine = BlindedPipelineEngine()
        self.vision_preprocessor = get_vision_preprocessor()
        self.mcp_config = get_mcp_config()
        self.tool_registry = ToolRegistry(self.mcp_config)
        self.agent_loop = AgentLoop(registry=self.tool_registry, config=self.mcp_config)

    def create_metered_completion(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        client_ip: str = "127.0.0.1",
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        max_tokens: int | None = None,
        enable_mcp: bool = True,
        client_tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        response_format: dict[str, Any] | None = None,
        on_progress: Any = None,
    ) -> tuple[str, str, int, int, int]:
        """Execute inference with atomic credit hold reservation and post-completion capture.

        Returns: (chat_id, completion_text, created_timestamp, tokens_prompt, tokens_completion)
        """
        canonical_model_id = resolve_model_id(model_id)
        requested_max = max_tokens or 512

        # Positive Authorization, Emergency Kill Switch & Permanent Ban Check (Global & Fleet-Scoped)
        try:
            from runtime.safety.dead_mans_switch import EmergencyKillTrippedError, get_lease_guard
            guard = get_lease_guard()
            if guard.is_tripped:
                raise EmergencyKillTrippedError(
                    f"Inference execution blocked: Global Platform Kill Switch is active ({guard.trip_reason})"
                )
            if account_id and guard.is_fleet_tripped(account_id):
                raise EmergencyKillTrippedError(
                    f"Inference execution blocked: Fleet '{account_id}' is emergency stopped/suspended ({guard.get_fleet_trip_reason(account_id)})"
                )
            if account_id:
                try:
                    from services.portal.passkey_routes import FLEET_ACCOUNT_STORE
                    if FLEET_ACCOUNT_STORE.is_fleet_banned(account_id):
                        info = FLEET_ACCOUNT_STORE.get_fleet_ban_info(account_id)
                        ban_reason = info.get("reason", "Administrative suspension") if info else "Administrative suspension"
                        raise EmergencyKillTrippedError(
                            f"Inference execution blocked: Fleet '{account_id}' is permanently suspended by Master Administrator ({ban_reason})"
                        )
                except Exception as _b_err:
                    if "EmergencyKillTrippedError" in type(_b_err).__name__:
                        raise
        except Exception as _ks_err:
            if "EmergencyKillTrippedError" in type(_ks_err).__name__:
                raise

        normalized_messages, est_prompt_tokens = self.vision_preprocessor.normalize_multimodal_messages(messages)

        hold = None
        if not is_teaser and not is_provider_self_compute:
            max_required_hold = calculate_max_charge_micro(canonical_model_id, est_prompt_tokens, requested_max)
            if hasattr(self.ledger, "create_hold"):
                hold = self.ledger.create_hold(
                    account_id=account_id,
                    amount_micro_units=max_required_hold,
                    model_id=canonical_model_id,
                )
            else:
                bal = self.ledger.get_balance(account_id) if hasattr(self.ledger, "get_balance") else 0
                if bal < max_required_hold:
                    raise InsufficientBalanceError(
                        f"Account '{account_id}' has insufficient balance ({bal} µ$) for completion (min hold {max_required_hold} µ$)"
                    )

        prompt_raw = json.dumps(normalized_messages)
        secure_buf = SecureMemoryBuffer(prompt_raw)
        try:
            backend_result = None
            if client_tools:
                with secure_buf.open_plaintext():
                    backend_result = self.backend.complete(
                        model_id=canonical_model_id,
                        messages=normalized_messages,
                        max_tokens=requested_max,
                        tools=client_tools,
                        tool_choice=tool_choice,
                        response_format=response_format,
                    )
                completion_text = backend_result.text
                tokens_prompt = backend_result.prompt_tokens
                tokens_completion = backend_result.completion_tokens
            elif enable_mcp and self.mcp_config.enabled:
                owner_id = None
                if account_id:
                    cleaned_k = str(account_id).strip()
                    if cleaned_k.startswith("acct_"):
                        owner_id = cleaned_k
                    else:
                        import hashlib
                        owner_id = "acct_" + hashlib.sha256(cleaned_k.encode("utf-8")).hexdigest()[:24]

                disabled_tools: list[str] = []
                if owner_id:
                    try:
                        from services.portal.passkey_routes import FLEET_ACCOUNT_STORE
                        disabled_tools = FLEET_ACCOUNT_STORE.get_mcp_disabled_tools(owner_id)
                    except Exception:
                        disabled_tools = []
                disabled_set = set(disabled_tools)

                def local_llm_caller(msg_list, tool_list):
                    nonlocal backend_result
                    try:
                        res = self.backend.complete(
                            model_id=canonical_model_id,
                            messages=msg_list,
                            max_tokens=requested_max,
                            tools=tool_list if tool_list else None,
                            response_format=response_format,
                        )
                    except TypeError:
                        try:
                            res = self.backend.complete(
                                model_id=canonical_model_id,
                                messages=msg_list,
                                max_tokens=requested_max,
                                tools=tool_list if tool_list else None,
                            )
                        except TypeError:
                            res = self.backend.complete(
                                model_id=canonical_model_id,
                                messages=msg_list,
                            )
                    backend_result = res
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": res.text,
                            }
                        }],
                        "usage": {
                            "prompt_tokens": res.prompt_tokens,
                            "completion_tokens": res.completion_tokens,
                        },
                    }

                enhanced_msgs = list(normalized_messages)
                has_tool_system = any(m.get("role") == "system" and "ComputeMesh AI" in str(m.get("content", "")) for m in enhanced_msgs)
                if not has_tool_system:
                    tool_prompt = (
                        "Du bist ComputeMesh AI mit integrierten Live-Werkzeugen (Model Context Protocol / MCP) und vollem Funktionsumfang (Code Interpreter, Vektorsuche/RAG, Langzeitgedächtnis, Bildgenerierung, Websuche & Live-APIs).\n"
                        "Wenn eine Frage Berechnungen, Python-Code, Datenanalyse, Tabellen, Diagramme, Wissensabfragen, Benutzerpräferenzen, aktuelle Daten, Websuche, Konzerte, Events, Wetter, Kurse oder Nachrichten erfordert, "
                        "rufe direkt das passende Tool auf (`execute_python_code`, `search_knowledge_base`, `get_user_memory`, `update_user_memory`, `generate_ai_image`, `check_url_safety`, `search_events`, `search_web`, `get_current_weather`, `get_live_news`, `get_market_quote`, `get_wikipedia_summary`, `calculate_math`, `get_time_and_calendar`, `generate_office_document`, `convert_data_to_markdown_table`, `list_available_tools`).\n\n"
                        "[VERBINDLICHE REGELN FÜR DIE ANTWORT]:\n"
                        "1. Sprache: Antworte IMMER in derselben Sprache wie die Frage (z.B. deutschsprachige Anfragen IMMER auf Deutsch beantworten).\n"
                        "2. KI-Synthese & Aufbereitung: Wenn Werkzeuge Live-Daten zurückliefern (z.B. Finanzkurse, Krypto, Marktdaten, Wetter, Websuche, Wikipedia), präsentiere die Daten niemals als unkommentierten oder unzusammenhängenden API-Dump. Formuliere eine flüssige, intelligente und kontextbezogene KI-Antwort. Gehe auf alle Aspekte der Benutzerfrage ein (z.B. aktueller Stand, 24h-Trend, Kursentwicklung, Einordnung und Vergleich) in verständlicher Sprache.\n"
                        "3. Tabellen & Struktur: Wenn der Nutzer nach einer Tabelle, Übersicht oder einem Vergleich fragt, MUSS das Ergebnis als formatierte Markdown-Tabelle (`| Spalte 1 | Spalte 2 | ... |`) aufbereitet werden."
                    )
                    try:
                        from services.memory.user_memory import get_user_memory_store
                        mem_summary = get_user_memory_store().get_memory_summary()
                        if mem_summary:
                            tool_prompt = f"{tool_prompt}\n\n{mem_summary}"
                    except Exception:
                        pass
                    enhanced_msgs.insert(0, {"role": "system", "content": tool_prompt})


                agent_res = self.agent_loop.run(
                    messages=enhanced_msgs,
                    model=canonical_model_id,
                    llm_caller=local_llm_caller,
                    is_owner=True,
                    disabled_tools=disabled_tools,
                    on_progress=on_progress,
                )
                completion_text = agent_res.final_content
                tokens_prompt = agent_res.prompt_tokens
                tokens_completion = agent_res.completion_tokens
            else:
                try:
                    # Billing must never precede execution. A failed or malformed runtime response
                    # is not a billable job and therefore cannot credit a provider.
                    with secure_buf.open_plaintext():
                        try:
                            backend_result = self.backend.complete(
                                model_id=canonical_model_id,
                                messages=normalized_messages,
                                max_tokens=requested_max,
                                response_format=response_format,
                            )
                        except TypeError:
                            try:
                                backend_result = self.backend.complete(
                                    model_id=canonical_model_id,
                                    messages=normalized_messages,
                                    max_tokens=requested_max,
                                )
                            except TypeError:
                                backend_result = self.backend.complete(
                                    model_id=canonical_model_id,
                                    messages=normalized_messages,
                                )
                    completion_text = backend_result.text
                    tokens_prompt = backend_result.prompt_tokens
                    tokens_completion = backend_result.completion_tokens
                finally:
                    secure_buf.zeroize()

            chat_id = f"chatcmpl-{secrets.token_hex(12)}"
            created_timestamp = int(time.time())

            if is_teaser:
                sess = self.teaser_manager.record_usage(client_ip, tokens=tokens_prompt + tokens_completion)
                rem = sess.remaining_requests
                max_req = self.teaser_manager.max_requests
                completion_text += f"\n\n---\n*⚡ ComputeMesh Free Teaser: Noch {rem}/{max_req} Anfragen übrig | {CONFIG.endpoints.domain}*"

            # Verified orchestrated execution takes precedence over operator-configured
            # shares. The ledger event also uses the durable orchestrator job id so the
            # financial event can be traced back to its reservation/evidence record.
            provider_shares = (
                list(backend_result.provider_shares)
                if (backend_result and getattr(backend_result, "provider_shares", None) is not None)
                else provider_shares_from_env()
            )
            billing_job_id = (backend_result.execution_job_id if backend_result else None) or chat_id
            fee_bps = 0 if is_provider_self_compute else None

            if not is_teaser and not is_provider_self_compute:
                if hold and hasattr(self.ledger, "capture_hold"):
                    self.ledger.capture_hold(
                        hold_id=hold.hold_id,
                        job_id=billing_job_id,
                        customer_account_id=account_id,
                        provider_shares=provider_shares,
                        model_id=canonical_model_id,
                        prompt_tokens=tokens_prompt,
                        completion_tokens=tokens_completion,
                        network_fee_bps=fee_bps,
                    )
                else:
                    self.ledger.record_job_execution(
                        job_id=billing_job_id,
                        customer_account_id=account_id,
                        provider_shares=provider_shares,
                        model_id=canonical_model_id,
                        prompt_tokens=tokens_prompt,
                        completion_tokens=tokens_completion,
                        network_fee_bps=fee_bps,
                    )

            cost_micro = calculate_token_charge_micro(
                model_id=canonical_model_id,
                prompt_tokens=tokens_prompt,
                completion_tokens=tokens_completion,
            )
            self.metrics.record_request(
                model=canonical_model_id,
                prompt_tokens=tokens_prompt,
                completion_tokens=tokens_completion,
                cost_micro_units=cost_micro,
                status_code=200,
            )

            # Record tokens into local metering store (if running on provider) and gateway telemetry registry
            try:
                from tools.appliance.token_metering import record_tokens
                record_tokens(prompt_tokens=tokens_prompt, completion_tokens=tokens_completion)
            except Exception:
                pass

            try:
                from services.gateway.dashboard import (
                    NODE_TELEMETRY_REGISTRY,
                    save_node_telemetry_registry,
                )
                total_job_toks = tokens_prompt + tokens_completion
                nodes_updated = False
                for p_share in (provider_shares or []):
                    p_node = None
                    if isinstance(p_share, (list, tuple)) and len(p_share) >= 1:
                        p_node = str(p_share[0])
                    elif isinstance(p_share, dict):
                        p_node = str(p_share.get("node_id") or p_share.get("provider_id") or "")
                    elif hasattr(p_share, "node_id"):
                        p_node = str(getattr(p_share, "node_id", ""))
                    if p_node and p_node in NODE_TELEMETRY_REGISTRY:
                        tel = NODE_TELEMETRY_REGISTRY[p_node].setdefault("telemetry", {})
                        tel["tokens_processed"] = int(tel.get("tokens_processed", 0) or 0) + total_job_toks
                        tel["earnings_cm"] = int(tel.get("earnings_cm", 0) or 0) + total_job_toks
                        nodes_updated = True
                if not nodes_updated:
                    for n_id, n_data in NODE_TELEMETRY_REGISTRY.items():
                        if not n_data.get("is_peer_relay", False) and n_data.get("updated_at"):
                            tel = n_data.setdefault("telemetry", {})
                            tel["tokens_processed"] = int(tel.get("tokens_processed", 0) or 0) + total_job_toks
                            tel["earnings_cm"] = int(tel.get("earnings_cm", 0) or 0) + total_job_toks
                            nodes_updated = True
                save_node_telemetry_registry(NODE_TELEMETRY_REGISTRY)
            except Exception:
                pass

            return chat_id, completion_text, created_timestamp, tokens_prompt, tokens_completion

        except Exception:
            if hold and hasattr(self.ledger, "release_hold"):
                try:
                    self.ledger.release_hold(hold.hold_id)
                except Exception:
                    pass
            raise
        finally:
            secure_buf.zeroize()

    @staticmethod
    def format_openai_response(
        *,
        chat_id: str,
        model_id: str,
        completion_text: str,
        created_timestamp: int,
        tokens_prompt: int,
        tokens_completion: int,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Formats standard OpenAI chat completion JSON response."""
        message: dict[str, Any] = {
            "role": "assistant",
            "content": completion_text or None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": chat_id,
            "object": "chat.completion",
            "created": created_timestamp,
            "model": model_id if isinstance(model_id, str) else "computemesh",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
            "usage": {
                "prompt_tokens": tokens_prompt,
                "completion_tokens": tokens_completion,
                "total_tokens": tokens_prompt + tokens_completion,
            },
        }

    @staticmethod
    def stream_openai_sse(
        *,
        chat_id: str,
        model_id: str,
        completion_text: str,
        created_timestamp: int,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> Generator[bytes, None, None]:
        """Yields Server-Sent Events (SSE) stream chunks for OpenAI clients."""
        if tool_calls:
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created_timestamp,
                "model": model_id,
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": completion_text or None,
                        "tool_calls": [dict(call, index=index) for index, call in enumerate(tool_calls)],
                    },
                    "finish_reason": "tool_calls",
                }],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
            return
        words = completion_text.split(" ")
        for i, word in enumerate(words):
            token_str = word + (" " if i < len(words) - 1 else "")
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created_timestamp,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": token_str},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
            time.sleep(0.01)

        final_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created_timestamp,
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"

    @staticmethod
    def format_ollama_chat_response(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> dict[str, Any]:
        """Formats non-streaming response for Ollama /api/chat."""
        return {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": {
                "role": "assistant",
                "content": completion_text,
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }

    @staticmethod
    def stream_ollama_chat_ndjson(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> Generator[bytes, None, None]:
        """Yields newline-delimited JSON stream chunks for Ollama /api/chat."""
        words = completion_text.split(" ")
        for i, word in enumerate(words):
            token_str = word + (" " if i < len(words) - 1 else "")
            chunk = {
                "model": model_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "message": {"role": "assistant", "content": token_str},
                "done": False,
            }
            yield (json.dumps(chunk, ensure_ascii=False) + "\n").encode("utf-8")
            time.sleep(0.01)

        final_chunk = {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }
        yield (json.dumps(final_chunk, ensure_ascii=False) + "\n").encode("utf-8")

    @staticmethod
    def format_ollama_generate_response(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> dict[str, Any]:
        """Formats non-streaming response for Ollama /api/generate."""
        return {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "response": completion_text,
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }

    @staticmethod
    def stream_ollama_generate_ndjson(
        *,
        model_id: str,
        completion_text: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> Generator[bytes, None, None]:
        """Yields newline-delimited JSON stream chunks for Ollama /api/generate."""
        words = completion_text.split(" ")
        for i, word in enumerate(words):
            token_str = word + (" " if i < len(words) - 1 else "")
            chunk = {
                "model": model_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "response": token_str,
                "done": False,
            }
            yield (json.dumps(chunk, ensure_ascii=False) + "\n").encode("utf-8")
            time.sleep(0.01)

        final_chunk = {
            "model": model_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "response": "",
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": tokens_prompt,
            "eval_count": tokens_completion,
        }
        yield (json.dumps(final_chunk, ensure_ascii=False) + "\n").encode("utf-8")

    def execute_chat_completion(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
        max_tokens: int | None = None,
        enable_mcp: bool = True,
        client_tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> tuple[dict[str, Any] | None, str | None, int]:
        try:
            chat_id, completion_text, created_ts, tok_p, tok_c = self.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
                enable_mcp=enable_mcp,
                client_tools=client_tools,
                tool_choice=tool_choice,
            )
            completion_text, tool_calls = _extract_client_tool_calls(completion_text, client_tools)
            res = self.format_openai_response(
                chat_id=chat_id,
                model_id=model_id,
                completion_text=completion_text,
                created_timestamp=created_ts,
                tokens_prompt=tok_p,
                tokens_completion=tok_c,
                tool_calls=tool_calls,
            )
            return (res, None, 200)
        except InsufficientBalanceError as exc:
            return (None, str(exc), 402)
        except InferenceBackendError as exc:
            return (None, sanitize_error_message(exc), 503)
        except Exception as exc:
            return (None, sanitize_error_message(exc), 500)

    def stream_chat_completions(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
        max_tokens: int | None = None,
        enable_mcp: bool = True,
        client_tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> Generator[bytes, None, None]:
        chat_id, completion_text, created_ts, _, _ = self.create_metered_completion(
            account_id=account_id,
            model_id=model_id,
            messages=messages,
            is_teaser=is_teaser,
            is_provider_self_compute=is_provider_self_compute,
            client_ip=client_ip,
            max_tokens=max_tokens,
            enable_mcp=enable_mcp,
            client_tools=client_tools,
            tool_choice=tool_choice,
        )
        completion_text, tool_calls = _extract_client_tool_calls(completion_text, client_tools)
        yield from self.stream_openai_sse(
            chat_id=chat_id,
            model_id=model_id,
            completion_text=completion_text,
            created_timestamp=created_ts,
            tool_calls=tool_calls,
        )

    def execute_ollama_chat(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any] | None, str | None, int]:
        try:
            _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
                enable_mcp=True,
            )
            res = self.format_ollama_chat_response(
                model_id=model_id,
                completion_text=completion_text,
                tokens_prompt=tok_p,
                tokens_completion=tok_c,
            )
            return (res, None, 200)
        except InsufficientBalanceError as exc:
            return (None, sanitize_error_message(exc), 402)
        except InferenceBackendError as exc:
            return (None, sanitize_error_message(exc), 503)
        except Exception as exc:
            return (None, sanitize_error_message(exc), 500)

    def stream_ollama_chat(
        self,
        *,
        account_id: str,
        model_id: str,
        messages: list[Any],
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
        max_tokens: int | None = None,
    ) -> Generator[bytes, None, None]:
        _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
            account_id=account_id,
            model_id=model_id,
            messages=messages,
            is_teaser=is_teaser,
            is_provider_self_compute=is_provider_self_compute,
            client_ip=client_ip,
            max_tokens=max_tokens,
            enable_mcp=True,
        )
        yield from self.stream_ollama_chat_ndjson(
            model_id=model_id,
            completion_text=completion_text,
            tokens_prompt=tok_p,
            tokens_completion=tok_c,
        )

    def execute_ollama_generate(
        self,
        *,
        account_id: str,
        model_id: str,
        prompt: str,
        images: list[str] | None = None,
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any] | None, str | None, int]:
        user_msg: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user_msg["images"] = images
        messages = [user_msg]
        try:
            _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
                account_id=account_id,
                model_id=model_id,
                messages=messages,
                is_teaser=is_teaser,
                is_provider_self_compute=is_provider_self_compute,
                client_ip=client_ip,
                max_tokens=max_tokens,
                enable_mcp=True,
            )
            res = self.format_ollama_generate_response(
                model_id=model_id,
                completion_text=completion_text,
                tokens_prompt=tok_p,
                tokens_completion=tok_c,
            )
            return (res, None, 200)
        except InsufficientBalanceError as exc:
            return (None, sanitize_error_message(exc), 402)
        except InferenceBackendError as exc:
            return (None, sanitize_error_message(exc), 503)
        except Exception as exc:
            return (None, sanitize_error_message(exc), 500)

    def stream_ollama_generate(
        self,
        *,
        account_id: str,
        model_id: str,
        prompt: str,
        images: list[str] | None = None,
        is_teaser: bool = False,
        is_provider_self_compute: bool = False,
        client_ip: str = "127.0.0.1",
        max_tokens: int | None = None,
    ) -> Generator[bytes, None, None]:
        user_msg: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            user_msg["images"] = images
        messages = [user_msg]
        _, completion_text, _, tok_p, tok_c = self.create_metered_completion(
            account_id=account_id,
            model_id=model_id,
            messages=messages,
            is_teaser=is_teaser,
            is_provider_self_compute=is_provider_self_compute,
            client_ip=client_ip,
            max_tokens=max_tokens,
            enable_mcp=True,
        )
        yield from self.stream_ollama_generate_ndjson(
            model_id=model_id,
            completion_text=completion_text,
            tokens_prompt=tok_p,
            tokens_completion=tok_c,
        )
