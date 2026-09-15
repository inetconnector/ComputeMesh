# SPDX-License-Identifier: Apache-2.0
"""Bounded autonomous tool-calling loop for ComputeMesh MCP tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import MCPConfig, get_mcp_config
from .tool_registry import ToolRegistry

# Subsystem Imports & Re-exports for 100% Backward Compatibility
from .formatting.reasoning_formatter import format_reasoning_and_thinking_blocks, THINKING_RE
from .formatting.tool_formatter import format_tool_content_if_json
from .parser.tool_call_parser import (
    XML_TOOL_CALL_RE,
    JSON_CODE_BLOCK_RE,
    RAW_JSON_TOOL_RE,
    MAX_TOOL_CALLS_PER_ITERATION,
    canonical_name,
    _canonical_name,
    parse_fallback_tool_calls,
    _fallback_tool_calls,
    decode_tool_arguments,
    _decode_arguments,
)
from .intent.entity_tokenizer import split_multi_entities, clean_entity_token
from .intent.intent_router import detect_direct_tool_intent, REFUSAL_KEYWORDS

MAX_AGENT_ITERATIONS = 20
MAX_TOOL_MESSAGE_CHARS = 100_000


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

        # Ensure tools guidance & persistent user memory are present in system instructions
        mem_info = ""
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
                "[VERBINDLICHE REGELN FÜR DIE ANTWORT]:\n"
                "1. Sprache: Antworte IMMER in derselben Sprache, in der die Benutzeranfrage gestellt wurde (z.B. deutschsprachige Prompts IMMER auf Deutsch beantworten).\n"
                "2. Tabellen & Struktur: Wenn der Benutzer nach einer Tabelle, Übersicht, Gegenüberstellung oder einem Vergleich fragt (z.B. Wetter/Kurse mehrerer Orte oder Kennzahlen), MUSS das Ergebnis als saubere Markdown-Tabelle (`| Spalte 1 | Spalte 2 | ... |`) formatiert werden.\n"
                "3. Vollständigkeit: Fasse alle abgerufenen Daten präzise zusammen und präsentiere generierte Bilder, Diagramme oder Links übersichtlich.\n\n"
                "[Chain-of-Thought Denkphase & Tool-Planung]:\n"
                "Bei komplexen, mehrteiligen oder recherchebedürftigen Anfragen kannst du einen einleitenden `<think>`-Block schreiben, um deine Schritte vor der Ausführung zu strukturieren:\n"
                "<think>\n"
                "1. Analyse der Benutzerabsicht und der benötigten Werkzeuge.\n"
                "2. Schritt 1: Recherche- oder Daten-Tool aufrufen.\n"
                "3. Schritt 2: Nach Erhalt der Daten Folge-Tool (z.B. `generate_ai_image` oder Python Plot) mit abgeleiteten Parametern aufrufen.\n"
                "4. Schritt 3: Gesamtergebnis klar und ansprechend in der gewünschten Struktur (z.B. Tabelle) formulieren.\n"
                "</think>\n\n"
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

        executed_records: List[ToolCallRecord] = []
        total_prompt_tok = 0
        total_comp_tok = 0
        last_assistant_content = ""

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

        # If no direct intent matched, check if resolving conversational references yields a research topic
        if not direct_intent and last_user_text and not has_images and len(curr_messages) > 1:
            try:
                from .builtin.context_resolver import resolve_contextual_query
                resolved_q, resolved_entity, was_resolved = resolve_contextual_query(last_user_text, curr_messages)
                if was_resolved and resolved_entity:
                    direct_intent = ("cross_source_knowledge_search", {"query": resolved_q})
            except Exception:
                pass
        if direct_intent and not any(m.get("role") == "tool" for m in curr_messages):
            fn_name, fn_args = direct_intent
            if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                call_id = "call_direct_preflight_1"
                _notify("intent_preflight", tool=fn_name, arguments=fn_args)
                tool_res = self.registry.execute_tool(fn_name, fn_args, is_owner=is_owner)
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
                _notify("preflight_completed", tool=fn_name)

        for iteration in range(1, max_iter + 1):
            _notify("iteration_start", iteration=iteration, max_iterations=max_iter)
            response = llm_caller(curr_messages, tools if tools else [])
            if not isinstance(response, dict):
                break
            usage = response.get("usage", {})
            if isinstance(usage, dict):
                total_prompt_tok += int(usage.get("prompt_tokens", 0) or 0)
                total_comp_tok += int(usage.get("completion_tokens", 0) or 0)

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
                _notify("loop_finished", final_records_count=len(executed_records))
                return AgentExecutionResult(
                    final_content=final,
                    messages=curr_messages,
                    tool_calls_executed=executed_records,
                    iterations=iteration,
                    model=model,
                    prompt_tokens=total_prompt_tok,
                    completion_tokens=total_comp_tok,
                    total_tokens=total_prompt_tok + total_comp_tok,
                )

            assistant_msg: Dict[str, Any] = {"role": "assistant", "tool_calls": tool_calls}
            if content:
                assistant_msg["content"] = content
            curr_messages.append(assistant_msg)

            # Execute tool calls in parallel with automatic concurrency and TTL caching
            _notify("tools_batch_executing", count=len(tool_calls), tools=[c.get("function", {}).get("name") for c in tool_calls])
            batch_results = self.registry.execute_tools_batch(tool_calls, is_owner=is_owner)
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
            _notify("tools_batch_completed", count=len(batch_results))

        final = format_tool_content_if_json(last_assistant_content)
        if not final and executed_records:
            final = format_tool_content_if_json(
                executed_records[-1].result if isinstance(executed_records[-1].result, str) else json.dumps(executed_records[-1].result, ensure_ascii=False)
            )
        return AgentExecutionResult(
            final_content=final,
            messages=curr_messages,
            tool_calls_executed=executed_records,
            iterations=max_iter,
            model=model,
            prompt_tokens=total_prompt_tok,
            completion_tokens=total_comp_tok,
            total_tokens=total_prompt_tok + total_comp_tok,
        )
