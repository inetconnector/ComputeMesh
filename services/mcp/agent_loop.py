# SPDX-License-Identifier: Apache-2.0
"""Bounded autonomous tool-calling loop for ComputeMesh MCP tools."""

from __future__ import annotations

import json
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
    ) -> AgentExecutionResult:
        try:
            requested_iterations = int(self.config.max_agent_iterations if max_iterations is None else max_iterations)
        except (TypeError, ValueError):
            requested_iterations = self.config.max_agent_iterations
        max_iter = max(1, min(MAX_AGENT_ITERATIONS, requested_iterations))

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
                "Du bist ComputeMesh AI. Du verfügst über volle OpenAI-Parität mit integrierten Live-Tools "
                "(Code Interpreter / Python Sandbox `execute_python_code`, Terminal Runner `run_terminal_command`, "
                "GitHub Integration Suite `github_get_repo`, `github_list_issues`, `github_get_pull_request`, `github_search_code`, "
                "HTTP API Client `execute_http_request`, Vektordatenbank / Document RAG `search_knowledge_base`, "
                "Echtzeit-Wetter `get_current_weather`, Börsen- und Kryptokurse `get_market_quote`, Web-Recherche `search_web`, "
                "Multi-Source Tiefenrecherche & Cross-Linguale Wikipedia `cross_source_knowledge_search`, `fetch_multilingual_wikipedia`, "
                "Ereignis-Zeitleisten `fetch_recent_timeline`, Faktenprüfung `verify_fact_multi_source`, Deep Cultural & Event Recherche `search_events`, "
                "Mathe `calculate_math` und Gedächtnis `update_user_memory`). "
                "Nutze diese Werkzeuge aktiv für präzise, topaktuelle und fundierte Antworten."
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

        for iteration in range(1, max_iter + 1):
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
            if (not tool_calls or is_refusal) and direct_intent and iteration == 1 and not executed_records:
                fn_name, fn_args = direct_intent
                if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                    tool_calls = [{
                        "id": f"call_auto_{len(executed_records)+1}",
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "arguments": json.dumps(fn_args, ensure_ascii=False),
                        },
                    }]

            # If no tools were called, this is the final answer
            if not tool_calls:
                final = format_tool_content_if_json(content)
                if not final and executed_records:
                    final = format_tool_content_if_json(
                        executed_records[-1].result if isinstance(executed_records[-1].result, str) else json.dumps(executed_records[-1].result, ensure_ascii=False)
                    )
                curr_messages.append({"role": "assistant", "content": final})
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
