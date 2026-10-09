# SPDX-License-Identifier: Apache-2.0
"""Bounded autonomous tool-calling loop for ComputeMesh MCP tools."""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from .config import MCPConfig, get_mcp_config

# Subsystem Imports & Re-exports for 100% Backward Compatibility
from .formatting.reasoning_formatter import THINKING_RE as THINKING_RE
from .formatting.reasoning_formatter import (
    format_reasoning_and_thinking_blocks as format_reasoning_and_thinking_blocks,
)
from .formatting.tool_formatter import format_tool_content_if_json
from .intent.entity_tokenizer import clean_entity_token as clean_entity_token
from .intent.entity_tokenizer import split_multi_entities as split_multi_entities
from .intent.intent_router import (
    REFUSAL_KEYWORDS,
    detect_compound_tool_intents,
    detect_direct_tool_intent,
)
from .parser.tool_call_parser import JSON_CODE_BLOCK_RE as JSON_CODE_BLOCK_RE
from .parser.tool_call_parser import (
    MAX_TOOL_CALLS_PER_ITERATION,
    _canonical_name,
    _fallback_tool_calls,
)
from .parser.tool_call_parser import RAW_JSON_TOOL_RE as RAW_JSON_TOOL_RE
from .parser.tool_call_parser import XML_TOOL_CALL_RE as XML_TOOL_CALL_RE
from .parser.tool_call_parser import _decode_arguments as _decode_arguments
from .parser.tool_call_parser import canonical_name as canonical_name
from .parser.tool_call_parser import decode_tool_arguments as decode_tool_arguments
from .parser.tool_call_parser import parse_fallback_tool_calls as parse_fallback_tool_calls
from .tool_registry import ToolRegistry

MAX_AGENT_ITERATIONS = 20
MAX_TOOL_MESSAGE_CHARS = 100_000
RESOURCE_USAGE_FIELDS = (
    "cpu_milliseconds",
    "gpu_milliseconds",
    "vram_byte_seconds",
    "network_bytes",
    "artifact_bytes",
    "external_cost_micros",
)


@dataclass
class ToolCallRecord:
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Any


@dataclass
class AgentExecutionResult:
    final_content: str
    messages: List[Dict[str, Any]]
    tool_calls_executed: List[ToolCallRecord] = field(default_factory=list)
    iterations: int = 1
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    resource_usage: Dict[str, int] = field(default_factory=dict)
    # Only bounded opaque execution identifiers; never model/provider policy data.
    provenance: Dict[str, List[str]] = field(default_factory=dict)


class AgentApprovalRequired(RuntimeError):
    """Raised internally when a durable side-effect approval pauses a turn."""

    def __init__(self, execution: AgentExecutionResult, approval_ids: List[str]) -> None:
        super().__init__("agent turn is waiting for approval")
        self.execution = execution
        self.approval_ids = tuple(str(value) for value in approval_ids)


class AgentControlRequested(RuntimeError):
    """Raised at a safe loop boundary when durable control asks us to stop."""

    def __init__(self, action: str, execution: AgentExecutionResult) -> None:
        super().__init__(f"agent turn control requested: {action}")
        self.action = str(action)
        self.execution = execution


class AgentLoop:
    """Orchestrates multi-turn autonomous tool execution loops with guardrails and token tracking."""

    def __init__(self, registry: Optional[ToolRegistry] = None, config: Optional[MCPConfig] = None):
        self.config = config or get_mcp_config()
        self.registry = registry or ToolRegistry(self.config)

    def run(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        llm_caller: Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]],
        is_owner: bool = True,
        max_iterations: Optional[int] = None,
        disabled_tools: Optional[List[str]] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        tool_broker: Any | None = None,
        should_stop: Optional[Callable[[], Optional[str]]] = None,
        on_checkpoint: Optional[Callable[[Dict[str, Any]], None]] = None,
        resume_state: Optional[Mapping[str, Any]] = None,
        cancel_event: Any | None = None,
    ) -> AgentExecutionResult:
        try:
            requested_iterations = int(self.config.max_agent_iterations if max_iterations is None else max_iterations)
        except (TypeError, ValueError):
            requested_iterations = self.config.max_agent_iterations
        max_iter = max(1, min(MAX_AGENT_ITERATIONS, requested_iterations))

        def _notify(event_name: str, **extra: Any) -> None:
            if on_progress:
                try:
                    on_progress({"event": event_name, **extra})
                except Exception:
                    pass

        raw_resume = dict(resume_state) if isinstance(resume_state, Mapping) else {}
        resume_phase = str(raw_resume.get("phase") or "")
        try:
            resume_iteration = max(0, int(raw_resume.get("iteration", 0) or 0))
        except (TypeError, ValueError):
            resume_iteration = 0
        resume_messages = raw_resume.get("messages")
        if isinstance(resume_messages, list) and all(isinstance(item, Mapping) for item in resume_messages):
            resume_messages = [dict(item) for item in resume_messages]
        else:
            resume_messages = None
        curr_messages = [dict(message) for message in messages]
        disabled_set = {
            _canonical_name(self.registry, str(name).strip())
            for name in (disabled_tools or [])
            if str(name).strip()
        }
        all_tools = self.registry.get_openai_tools(is_owner=is_owner)
        tools = [
            tool for tool in all_tools
            if _canonical_name(self.registry, tool.get("function", {}).get("name", "")) not in disabled_set
        ]

        # Legacy persistent-memory prompt injection is retained only in
        # disabled/shadow mode for backwards compatibility. Active Agents Platform
        # injects scoped memory as UNTRUSTED_DATA at user authority in runtime.py.
        mem_info = ""
        if not (
            self.config.agents_platform_enabled
            and not self.config.agents_platform_shadow_mode
        ):
            try:
                from ..memory import get_user_memory_store
                mem_summary = get_user_memory_store().get_memory_summary()
                if mem_summary and "Keine gespeicherten" not in mem_summary:
                    mem_info = f"\n\n[Persistentes Benutzer-Gedächtnis & Fakten]:\n{mem_summary}"
            except Exception:
                pass

        if tools or mem_info:
            has_system = any(m.get("role") == "system" for m in curr_messages)
            sys_guidance = (
                "Du bist ComputeMesh AI, ein hochintelligenter, autonomer KI-Assistent mit integrierten Live-Tools "
                "(Model Context Protocol / OpenAI Tool-Calling). Dir stehen u.a. folgende Werkzeuge zur Verfügung:\n"
                "- Bildgenerierung: `generate_ai_image` (generiert fotorealistische, hochauflösende Bilder)\n"
                "- Live-Nachrichten & Feeds: `get_live_news` (Tagesschau, Heise, Reuters, etc.)\n"
                "- Web-Suche & Recherche: `search_web`, `cross_source_knowledge_search`, `fetch_multilingual_wikipedia`, `get_wikipedia_summary`\n"
                "- Finanzen & Kurse: `get_market_quote` (Aktien, Krypto, Währungen)\n"
                "- Wetter & Prognosen: `get_current_weather`, `get_weather_forecast`\n"
                "- Office & Tabellen: `generate_office_document`, `parse_office_document`, `convert_data_to_markdown_table`, `analyze_data_table`\n"
                "- Code Interpreter & Sandbox: `execute_python_code`, `run_terminal_command`\n"
                "- GitHub Suite: `github_get_repo`, `github_list_issues`, `github_get_pull_request`, `github_search_code`\n"
                "- HTTP API Client: `execute_http_request`\n"
                "- Vektordatenbank & RAG: `search_knowledge_base`\n"
                "- Rechnen & Zeit: `calculate_math`, `get_time_and_calendar`\n"
                "- Gedächtnis & Profil: `get_user_memory`, `update_user_memory`\n\n"
                "- Universal Skill Execution (owner-only): `execute_universal_skill` für komplexe Aufgaben; nutze `operation=audit` oder `operation=improve` nur als Review-Vorschlag und aktiviere keine Änderungen ohne Freigabe.\n\n"
                "[VERBINDLICHE REGELN FÜR DIE ANTWORT]:\n"
                "1. Sprache: Antworte IMMER in derselben Sprache, in der die Benutzeranfrage gestellt wurde (z.B. deutschsprachige Prompts IMMER auf Deutsch beantworten).\n"
                "2. KI-Synthese & Aufbereitung: Wenn Werkzeuge Live-Daten zurückliefern (z.B. Finanzkurse, Krypto, Marktdaten, Wetter, Websuche, Wikipedia), präsentiere die Daten niemals als unkommentierten oder unzusammenhängenden API-Dump. Formuliere eine flüssige, intelligente und kontextbezogene KI-Antwort. Gehe auf alle Aspekte der Benutzerfrage ein (z.B. aktueller Stand, 24h-Trend, Kursentwicklung, Einordnung und Vergleich) in verständlicher Sprache.\n"
                "3. Tabellen & Struktur: Wenn der Benutzer nach einer Tabelle, Übersicht, Gegenüberstellung oder einem Vergleich fragt (z.B. Wetter/Kurse mehrerer Orte oder Kennzahlen), MUSS das Ergebnis als saubere Markdown-Tabelle (`| Spalte 1 | Spalte 2 | ... |`) formatiert werden.\n"
                "4. Vollständigkeit: Fasse alle abgerufenen Daten präzise zusammen und präsentiere generierte Bilder, Diagramme oder Links übersichtlich.\n\n"
                "[Tool-Planung]:\n"
                "Plane komplexe Tool-Schritte intern und gib nur knappe, überprüfbare Fortschritts- oder Ergebnisinformationen aus. "
                "Gib keine privaten Gedankengänge und keine `<think>`-Blöcke aus.\n\n"
                "[Tool-Calling Format]:\n"
                "Rufe Werkzeuge entweder über native Function Calls oder direkt im JSON/XML-Format auf:\n"
                "<tool_call>{\"name\": \"get_live_news\", \"arguments\": {\"topic\": \"allgemein\"}}</tool_call>\n"
                "<tool_call>{\"name\": \"generate_ai_image\", \"arguments\": {\"prompt\": \"Motivbeschreibung\", \"style\": \"photorealistic\"}}</tool_call>\n"
                f"{mem_info}"
            )
            if not has_system:
                curr_messages.insert(0, {"role": "system", "content": sys_guidance})
            elif mem_info:
                for m in curr_messages:
                    if m.get("role") == "system":
                        if "[Persistentes Benutzer-Gedächtnis" not in str(m.get("content", "")):
                            m["content"] = str(m.get("content", "")) + mem_info
                        break

        # A private execution checkpoint contains the exact in-flight message
        # sequence. It is applied after normal system guidance so a resumed
        # turn cannot accumulate a second injected system prompt.
        if resume_messages is not None:
            curr_messages = resume_messages

        executed_records: List[ToolCallRecord] = []
        raw_records = raw_resume.get("tool_records")
        if isinstance(raw_records, list):
            for raw_record in raw_records[:128]:
                if not isinstance(raw_record, Mapping):
                    continue
                record_id = str(raw_record.get("id") or "")
                record_name = str(raw_record.get("name") or "")
                arguments = raw_record.get("arguments")
                if record_id and record_name and isinstance(arguments, Mapping):
                    executed_records.append(ToolCallRecord(
                        id=record_id[:160],
                        name=record_name[:256],
                        arguments=dict(arguments),
                        result=raw_record.get("result"),
                    ))
        def _restored_count(name: str) -> int:
            value = raw_resume.get(name, 0)
            return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

        total_prompt_tok = _restored_count("prompt_tokens")
        total_comp_tok = _restored_count("completion_tokens")
        total_resource_usage = {
            field: _restored_count(field)
            for field in RESOURCE_USAGE_FIELDS
        }
        execution_provenance: Dict[str, List[str]] = {
            "execution_job_ids": [],
            "execution_node_ids": [],
        }
        restored_provenance = raw_resume.get("provenance")
        if isinstance(restored_provenance, Mapping):
            for field in execution_provenance:
                values = restored_provenance.get(field)
                if isinstance(values, (list, tuple)):
                    execution_provenance[field] = [
                        str(value).strip()[:160]
                        for value in values[:32]
                        if isinstance(value, str) and 1 <= len(value.strip()) <= 160
                    ]
        last_assistant_content = str(raw_resume.get("last_assistant_content") or "")[:MAX_TOOL_MESSAGE_CHARS]
        preflight_completed = bool(raw_resume.get("preflight_completed", False))

        def _record_resource_usage(usage: Any) -> None:
            if not isinstance(usage, dict):
                return
            for field in RESOURCE_USAGE_FIELDS:
                value = usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    total_resource_usage[field] += int(value)

        def _record_execution_provenance(response: Any) -> None:
            if not isinstance(response, dict):
                return
            provenance = response.get("provenance")
            if not isinstance(provenance, dict):
                return
            for field, max_length in (("execution_job_ids", 32), ("execution_node_ids", 32)):
                values = provenance.get(field)
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, (list, tuple, set, frozenset)):
                    continue
                for value in values:
                    if not isinstance(value, str):
                        continue
                    value = value.strip()
                    if not 1 <= len(value) <= 160:
                        continue
                    if value not in execution_provenance[field]:
                        execution_provenance[field].append(value)
                    if len(execution_provenance[field]) >= max_length:
                        break

        def _execution_result(*, iterations: int, final_content: str = "") -> AgentExecutionResult:
            return AgentExecutionResult(
                final_content=final_content,
                messages=curr_messages,
                tool_calls_executed=executed_records,
                iterations=iterations,
                model=model,
                prompt_tokens=total_prompt_tok,
                completion_tokens=total_comp_tok,
                total_tokens=total_prompt_tok + total_comp_tok,
                resource_usage=dict(total_resource_usage),
                provenance={
                    key: list(values)
                    for key, values in execution_provenance.items()
                    if values
                },
            )

        def _checkpoint(
            *,
            phase: str,
            iteration: int,
            pending_tool_calls: List[Dict[str, Any]] | None = None,
            final_content: str = "",
        ) -> None:
            if on_checkpoint is None:
                return
            snapshot: Dict[str, Any] = {
                "schema_version": 1,
                "phase": str(phase),
                "iteration": int(max(0, iteration)),
                "messages": [dict(message) for message in curr_messages],
                "tool_records": [
                    {
                        "id": record.id,
                        "name": record.name,
                        "arguments": dict(record.arguments),
                        "result": record.result,
                    }
                    for record in executed_records[-128:]
                ],
                "prompt_tokens": total_prompt_tok,
                "completion_tokens": total_comp_tok,
                "provenance": {
                    key: list(values)
                    for key, values in execution_provenance.items()
                    if values
                },
                "resource_usage": dict(total_resource_usage),
                "last_assistant_content": last_assistant_content,
                "preflight_completed": preflight_completed,
                "pending_tool_calls": [dict(call) for call in (pending_tool_calls or [])[:MAX_TOOL_CALLS_PER_ITERATION]],
                "final_content": str(final_content or "")[:MAX_TOOL_MESSAGE_CHARS],
            }
            encoded_size = len(json.dumps(snapshot, ensure_ascii=False, default=str).encode("utf-8"))
            if encoded_size > 4 * 1024 * 1024:
                raise ValueError("agent execution checkpoint exceeds the 4 MiB limit")
            on_checkpoint(snapshot)

        def _check_control() -> None:
            if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
                raise AgentControlRequested(
                    "cancel",
                    _execution_result(iterations=0, final_content=format_tool_content_if_json(last_assistant_content)),
                )
            if should_stop is None:
                return
            action = should_stop()
            if action not in {"pause", "cancel"}:
                return
            raise AgentControlRequested(
                action,
                _execution_result(iterations=0, final_content=format_tool_content_if_json(last_assistant_content)),
            )

        _check_control()

        if resume_phase == "completed":
            return _execution_result(
                iterations=resume_iteration,
                final_content=str(raw_resume.get("final_content") or last_assistant_content),
            )

        # Find latest user prompt and check for images
        last_user_text = ""
        has_images = False
        for m in reversed(curr_messages):
            if bool(m.get("images")) or bool(m.get("_processed_images")):
                has_images = True
            c = m.get("content")
            if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") in ("image_url", "image") for p in c):
                has_images = True
            if m.get("role") == "user" and not last_user_text:
                last_user_text = str(m.get("content") or "")

        # Check proactive pre-flight intent only for pure text queries without images
        direct_intent = detect_direct_tool_intent(last_user_text, self.registry) if (last_user_text and not has_images) else None

        # If no direct intent matched, check if resolving conversational references yields a concrete intent
        if not direct_intent and last_user_text and not has_images and len(curr_messages) > 1:
            try:
                from .builtin.context_resolver import resolve_contextual_query
                resolved_q, resolved_entity, was_resolved = resolve_contextual_query(last_user_text, curr_messages)
                if was_resolved and resolved_q:
                    direct_intent = detect_direct_tool_intent(resolved_q, self.registry)
                    if not direct_intent and any(w in resolved_q.lower() for w in ("recherchiere", "tiefenrecherche", "deep research", "hintergründe", "ereignisse")):
                        direct_intent = ("cross_source_knowledge_search", {"query": resolved_q})
            except Exception:
                pass
        if direct_intent and not any(m.get("role") == "tool" for m in curr_messages):
            fn_name, fn_args = direct_intent
            if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                _check_control()
                call_id = "call_direct_preflight_1"
                _notify("intent_preflight", tool=fn_name, arguments=fn_args)
                tool_res = (
                    tool_broker.execute_tool(fn_name, fn_args, call_id=call_id, is_owner=is_owner)
                    if tool_broker is not None
                    else self.registry.execute_tool(fn_name, fn_args, is_owner=is_owner)
                )
                executed_records.append(ToolCallRecord(id=call_id, name=fn_name, arguments=fn_args, result=tool_res))
                output_str = tool_res if isinstance(tool_res, str) else json.dumps(tool_res, ensure_ascii=False)
                if len(output_str) > MAX_TOOL_MESSAGE_CHARS:
                    output_str = output_str[:MAX_TOOL_MESSAGE_CHARS] + "\n[Tool-Ausgabe gekürzt]"

                curr_messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": json.dumps(fn_args, ensure_ascii=False),
                        }
                    }]
                })
                curr_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": output_str,
                })
                if isinstance(tool_res, dict) and tool_res.get("status") == "confirmation_required":
                    provenance = tool_res.get("provenance") if isinstance(tool_res.get("provenance"), dict) else {}
                    approval_id = str(provenance.get("approval_id") or "")
                    if approval_id:
                        _notify("approval_required", tool=fn_name, call_id=call_id, approval_id=approval_id)
                        raise AgentApprovalRequired(
                            _execution_result(iterations=0),
                            [approval_id],
                        )
                preflight_completed = True
                _notify("preflight_completed", tool=fn_name)
                _checkpoint(phase="next_model", iteration=0)

        pending_resume_tool_calls = raw_resume.get("pending_tool_calls")
        if not isinstance(pending_resume_tool_calls, list):
            pending_resume_tool_calls = None
        resume_model_complete = resume_phase == "model_complete"
        if resume_model_complete and not pending_resume_tool_calls:
            return _execution_result(
                iterations=resume_iteration,
                final_content=str(raw_resume.get("final_content") or last_assistant_content),
            )
        start_iteration = max(1, resume_iteration if resume_model_complete else resume_iteration + 1)
        for iteration in range(start_iteration, max_iter + 1):
            _check_control()
            _notify("iteration_start", iteration=iteration, max_iterations=max_iter)
            # A direct intent has already executed the authoritative live tool.
            # Give the model only the resulting tool message for synthesis; if
            # it receives the full registry here it can invent an unrelated
            # second call instead of answering from the fresh result.
            _check_control()
            resumed_model_response = False
            if resume_model_complete:
                response = {
                    "choices": [{
                        "message": {
                            "content": last_assistant_content,
                            "tool_calls": pending_resume_tool_calls,
                        },
                    }],
                }
                resume_model_complete = False
                pending_resume_tool_calls = None
                resumed_model_response = True
            else:
                llm_tools = [] if preflight_completed else (tools if tools else [])
                try:
                    parameters = inspect.signature(llm_caller).parameters
                    accepts_cancel = "cancel_event" in parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_cancel = False
                try:
                    response = (
                        llm_caller(curr_messages, llm_tools, cancel_event=cancel_event)
                        if accepts_cancel
                        else llm_caller(curr_messages, llm_tools)
                    )
                except AgentControlRequested:
                    raise
                except Exception as exc:
                    if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
                        raise AgentControlRequested(
                            "cancel",
                            _execution_result(iterations=iteration - 1, final_content=format_tool_content_if_json(last_assistant_content)),
                        ) from exc
                    raise
                _check_control()
            if not isinstance(response, dict):
                break
            _record_execution_provenance(response)
            usage = response.get("usage", {})
            if isinstance(usage, dict):
                total_prompt_tok += int(usage.get("prompt_tokens", 0) or 0)
                total_comp_tok += int(usage.get("completion_tokens", 0) or 0)
                _record_resource_usage(usage)

            choices = response.get("choices", [])
            if not isinstance(choices, list) or not choices:
                break
            choice = choices[0] if isinstance(choices[0], dict) else {}
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            message = message if isinstance(message, dict) else {}
            content = str(message.get("content") or "")
            last_assistant_content = content or last_assistant_content
            raw_tool_calls = message.get("tool_calls") or []
            tool_calls = list(raw_tool_calls) if isinstance(raw_tool_calls, list) else []
            if not tool_calls:
                tool_calls = _fallback_tool_calls(content, self.registry)
            else:
                tool_calls = tool_calls[:MAX_TOOL_CALLS_PER_ITERATION]

            # Check if model emitted refusal or no tool call despite clear user tool intent
            is_refusal = any(kw in content.lower() for kw in REFUSAL_KEYWORDS)
            if (not tool_calls or is_refusal) and not has_images and iteration == 1 and not executed_records:
                compound_intents = detect_compound_tool_intents(last_user_text, self.registry)
                if compound_intents:
                    auto_calls = []
                    for idx, (fn_name, fn_args) in enumerate(compound_intents):
                        if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                            auto_calls.append({
                                "id": f"call_auto_{len(executed_records)+idx+1}",
                                "type": "function",
                                "function": {
                                    "name": fn_name,
                                    "arguments": json.dumps(fn_args, ensure_ascii=False),
                                },
                            })
                    if auto_calls:
                        tool_calls = auto_calls
                else:
                    target_intent = direct_intent or detect_direct_tool_intent(last_user_text, self.registry, allow_compound=True)
                    if not target_intent:
                        if any(w in last_user_text.lower() for w in ("nachrichten", "news", "schlagzeilen", "tagesschau", "aktuell")):
                            target_intent = ("get_live_news", {"topic": "allgemein"})
                        elif any(w in last_user_text.lower() for w in ("btc", "bitcoin", "eth", "krypto", "aktie")):
                            target_intent = ("get_market_quote", {"asset": "BTC"})
                        elif any(w in last_user_text.lower() for w in ("wetter", "weather")):
                            target_intent = ("get_current_weather", {"city": "Berlin"})
                        elif any(w in last_user_text.lower() for w in ("generiere ein bild", "erstelle ein bild", "male ein bild", "zeichne ein bild", "generate an image", "create an image")):
                            target_intent = ("generate_ai_image", {"prompt": last_user_text, "style": "photorealistic"})
                    if target_intent:
                        fn_name, fn_args = target_intent
                        if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                            tool_calls = [{
                                "id": f"call_auto_{len(executed_records)+1}",
                                "type": "function",
                                "function": {
                                    "name": fn_name,
                                    "arguments": json.dumps(fn_args, ensure_ascii=False),
                                },
                            }]

            # Multi-step chained fallback: If user requested an image and previous data tool succeeded, but LLM refused or did not call image tool
            user_wants_image = any(w in last_user_text.lower() for w in ("bild", "foto", "image", "male", "zeichne", "generiere ein bild", "erstelle ein bild", "paint", "draw", "picture", "gemälde"))
            has_image_tool_run = any(r.name in ("generate_ai_image", "generate_image") for r in executed_records)
            if (not tool_calls or is_refusal) and not has_images and user_wants_image and not has_image_tool_run and executed_records:
                last_rec = executed_records[-1]
                prev_data = last_rec.result
                if isinstance(prev_data, str):
                    try:
                        prev_data = json.loads(prev_data)
                    except Exception:
                        pass
                derived_prompt = ""
                if isinstance(prev_data, dict):
                    articles = prev_data.get("articles", [])
                    if not articles and "feeds" in prev_data:
                        for feed in prev_data.get("feeds", []):
                            if isinstance(feed, dict) and feed.get("articles"):
                                articles.extend(feed["articles"])
                    if articles:
                        headline_titles = []
                        for a in articles[:4]:
                            raw_t = (a.get("title") or "").strip()
                            clean_t = re.sub(r"\s+[\-\|]\s+[^-\|]+$", "", raw_t).strip()
                            if clean_t and clean_t not in headline_titles:
                                headline_titles.append(clean_t)
                        if len(headline_titles) > 1:
                            joined_headlines = " ; ".join(headline_titles[:3])
                            derived_prompt = f"Editorial conceptual artwork montage symbolizing today's major headlines: {joined_headlines}. High-impact visual journalism, surreal symbolic composition, dramatic lighting, modern press aesthetic, 8k"
                        else:
                            top_a = articles[0]
                            t = top_a.get("title", "").strip()
                            s = (top_a.get("summary") or top_a.get("description") or "").strip()
                            derived_prompt = f"Editorial cinematic conceptual artwork depicting breaking news: {t}. {s[:160]}"
                    elif "symbol" in prev_data and ("price" in prev_data or "price_usd" in prev_data):
                        sym = prev_data.get("symbol", "Asset")
                        pr = prev_data.get("price", prev_data.get("price_usd", ""))
                        derived_prompt = f"Futuristic high-tech visual of {sym} trading at {pr} with financial chart lines and digital neon waves"
                    elif "temperature_celsius" in prev_data:
                        loc = prev_data.get("location") or prev_data.get("city") or "City"
                        cond = prev_data.get("condition", "clear sky")
                        temp = prev_data.get("temperature_celsius", 20)
                        derived_prompt = f"Scenic atmospheric landscape of {loc} with {cond} weather, {temp} degrees celsius, cinematic lighting, 8k"
                    elif "title" in prev_data and "summary" in prev_data:
                        derived_prompt = f"Illustrative conceptual art representing {prev_data.get('title')}: {prev_data.get('summary', '')[:140]}"
                if not derived_prompt:
                    derived_prompt = last_user_text
                style_val = "photorealistic"
                if any(w in last_user_text.lower() for w in ("gemälde", "painting", "artistic", "ölgemälde", "künstlerisch")):
                    style_val = "artistic"
                elif any(w in last_user_text.lower() for w in ("anime", "manga", "comic")):
                    style_val = "anime"
                elif any(w in last_user_text.lower() for w in ("cyberpunk", "sci-fi", "futuristisch", "neon")):
                    style_val = "cyberpunk"
                elif any(w in last_user_text.lower() for w in ("cinematic", "film", "kino", "movie")):
                    style_val = "cinematic"

                if "generate_ai_image" not in disabled_set and self.registry.get_tool("generate_ai_image"):
                    tool_calls = [{
                        "id": f"call_img_chained_{len(executed_records)+1}",
                        "type": "function",
                        "function": {
                            "name": "generate_ai_image",
                            "arguments": json.dumps({"prompt": derived_prompt, "style": style_val}, ensure_ascii=False),
                        },
                    }]

            # If no tools were called, this is the final answer
            if not tool_calls:
                is_json_explaining = bool(re.search(
                    r"\b(?:is\s+a\s+json\s+object|json\s+object\s+(?:that\s+)?contains|the\s+provided\s+json|the\s+response\s+you\s+provided|here(?:'s|\s+is)\s+the\s+breakdown|quotes\s+array|this\s+array\s+contains|the\s+(?:open-meteo|yahoo\s+finance|coingecko|api|tool)\s+(?:api\s+)?(?:provides|returned|contains)|bereitgestellte\s+json|json-objekt\s+enthält|die\s+open-meteo\s+api)\b",
                    content,
                    re.IGNORECASE,
                ))
                user_wants_table = any(w in last_user_text.lower() for w in ("tabelle", "tabellarisch", "table", "im vergleich", "vergleich", "gegenüberstellung", "matrix"))
                missing_table_structure = user_wants_table and "|" not in content
                has_image_tool_run = any(r.name in ("generate_ai_image", "generate_image") for r in executed_records)
                missing_image_render = has_image_tool_run and "![" not in content
                if (is_refusal or is_json_explaining or missing_table_structure or missing_image_render or not content.strip()) and executed_records:
                    parts = []
                    for rec in executed_records:
                        t_res = rec.result if isinstance(rec.result, str) else json.dumps(rec.result, ensure_ascii=False)
                        f_fmt = format_tool_content_if_json(t_res)
                        if f_fmt and f_fmt not in parts:
                            parts.append(f_fmt)
                    final = "\n\n---\n\n".join(parts) if parts else format_tool_content_if_json(content)
                else:
                    final = format_tool_content_if_json(content)
                    if (not final or is_refusal or is_json_explaining or missing_image_render) and executed_records:
                        parts = []
                        for rec in executed_records:
                            t_res = rec.result if isinstance(rec.result, str) else json.dumps(rec.result, ensure_ascii=False)
                            f_fmt = format_tool_content_if_json(t_res)
                            if f_fmt and f_fmt not in parts:
                                parts.append(f_fmt)
                        final = "\n\n---\n\n".join(parts) if parts else format_tool_content_if_json(content)
                curr_messages.append({"role": "assistant", "content": final})
                _checkpoint(phase="completed", iteration=iteration, final_content=final)
                _notify("loop_finished", final_records_count=len(executed_records))
                return _execution_result(iterations=iteration, final_content=final)

            assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
            if content:
                assistant_msg["content"] = content
            if not resumed_model_response:
                curr_messages.append(assistant_msg)
            _checkpoint(phase="model_complete", iteration=iteration, pending_tool_calls=tool_calls)

            # Execute tool calls in parallel with automatic concurrency and TTL caching
            _check_control()
            _notify("tools_batch_executing", count=len(tool_calls), tools=[c.get("function", {}).get("name") for c in tool_calls])
            batch_results = (
                tool_broker.execute_tools_batch(tool_calls, is_owner=is_owner)
                if tool_broker is not None
                else self.registry.execute_tools_batch(tool_calls, is_owner=is_owner)
            )
            for res_item in batch_results:
                call_id = res_item["id"]
                fn_name = res_item["name"]
                record_args = res_item["arguments"]
                tool_output = res_item["result"]

                canonical = _canonical_name(self.registry, fn_name)
                if canonical in disabled_set:
                    tool_output = {"error": f"Tool '{canonical}' ist für diese Flotte deaktiviert."}

                executed_records.append(ToolCallRecord(
                    id=call_id,
                    name=fn_name,
                    arguments=record_args,
                    result=tool_output,
                ))
                output_str = tool_output if isinstance(tool_output, str) else json.dumps(tool_output, ensure_ascii=False)
                if len(output_str) > MAX_TOOL_MESSAGE_CHARS:
                    output_str = output_str[:MAX_TOOL_MESSAGE_CHARS] + "\n[Tool-Ausgabe gekürzt]"
                curr_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": output_str,
                })
            _checkpoint(phase="next_model", iteration=iteration)
            approval_ids = []
            for res_item in batch_results:
                tool_output = res_item.get("result")
                if isinstance(tool_output, dict) and tool_output.get("status") == "confirmation_required":
                    provenance = tool_output.get("provenance") if isinstance(tool_output.get("provenance"), dict) else {}
                    approval_id = str(provenance.get("approval_id") or "")
                    if approval_id:
                        approval_ids.append(approval_id)
            if approval_ids:
                _notify("approval_required", approval_ids=approval_ids)
                raise AgentApprovalRequired(
                    _execution_result(iterations=iteration),
                    approval_ids,
                )
            _notify("tools_batch_completed", count=len(batch_results))
            _check_control()

        final = format_tool_content_if_json(last_assistant_content)
        if not final and executed_records:
            final = format_tool_content_if_json(
                executed_records[-1].result if isinstance(executed_records[-1].result, str) else json.dumps(executed_records[-1].result, ensure_ascii=False)
            )
        _checkpoint(phase="completed", iteration=max_iter, final_content=final)
        return _execution_result(iterations=max_iter, final_content=final)
