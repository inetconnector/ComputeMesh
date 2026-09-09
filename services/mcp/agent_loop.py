# SPDX-License-Identifier: Apache-2.0
"""Bounded autonomous tool-calling loop for ComputeMesh MCP tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import MCPConfig, get_mcp_config
from .tool_registry import ToolRegistry

XML_TOOL_CALL_RE = re.compile(r"<tool_call>\s*({.*?})(?:\s*</tool_call>|\s*$)", re.DOTALL)
JSON_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{\s*\"(?:name|tool|function)\"\s*:\s*\"[a-zA-Z0-9_-]+\".*?\})\s*```", re.DOTALL)
RAW_JSON_TOOL_RE = re.compile(r"\{\s*\"(?:name|tool|function)\"\s*:\s*\"([a-zA-Z0-9_-]+)\"\s*,\s*\"(?:arguments|parameters)\"\s*:\s*(\{.*?\})\s*\}", re.DOTALL)
MAX_AGENT_ITERATIONS = 20
MAX_TOOL_CALLS_PER_ITERATION = 16
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


def format_tool_content_if_json(content: str) -> str:
    """Format a few common raw JSON tool responses for direct user display."""
    cleaned = str(content or "").strip()
    if not (cleaned.startswith("{") and cleaned.endswith("}")):
        return str(content or "")
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return str(content or "")

        if "temperature_celsius" in data or "condition" in data:
            loc = data.get("location", "Ort")
            temp = data.get("temperature_celsius", "N/A")
            app_temp = data.get("apparent_temperature_celsius")
            cond = data.get("condition", "Unbekannt")
            hum = data.get("humidity_percent", "N/A")
            wind = data.get("wind_speed_kmh", "N/A")
            reg = data.get("region")
            country = data.get("country")
            loc_str = f"{loc} ({reg}, {country})" if reg and country else loc
            result = f"Aktuelles Live-Wetter für **{loc_str}**:\n"
            result += f"- **Bedingungen:** {cond}\n"
            result += f"- **Temperatur:** {temp} °C" + (f" (gefühlt {app_temp} °C)\n" if app_temp is not None else "\n")
            result += f"- **Luftfeuchtigkeit:** {hum} %\n"
            result += f"- **Windgeschwindigkeit:** {wind} km/h\n"
            if "precipitation_mm" in data:
                result += f"- **Niederschlag:** {data['precipitation_mm']} mm\n"
            if data.get("source"):
                result += f"- **Quelle:** {data['source']}"
            return result.strip()

        if "price_usd" in data or "symbol" in data:
            symbol = str(data.get("symbol", "")).upper()
            name = data.get("name", symbol)
            price = data.get("price_usd") or data.get("price_eur") or data.get("price")
            change_24h = data.get("change_24h_percent")
            result = f"Aktueller Börsen-/Kryptokurs für **{name} ({symbol})**:\n"
            result += f"- **Preis:** ${price:,.2f}" if isinstance(price, (int, float)) else f"- **Preis:** {price}\n"
            if change_24h is not None:
                result += f"\n- **24h-Veränderung:** {change_24h:+.2f} %"
            return result.strip()

        if "articles" in data or ("topic" in data and "items" in data):
            articles = data.get("articles") or data.get("items") or []
            topic = data.get("topic", "Aktuelle Nachrichten")
            result = f"Aktuelle Nachrichten (**{topic}**):\n\n"
            if isinstance(articles, list):
                for index, article in enumerate(articles[:5], 1):
                    if not isinstance(article, dict):
                        continue
                    title = article.get("title", "")
                    source = article.get("source", "")
                    url = article.get("link", "")
                    source_text = f" *({source})*" if source else ""
                    result += f"{index}. [{title}]({url}){source_text}\n" if url else f"{index}. **{title}**{source_text}\n"
            return result.strip()

        if "title" in data and "summary" in data:
            title = data.get("title", "")
            summary = data.get("summary", "")
            url = data.get("url", "")
            result = f"**{title}** (Wikipedia):\n\n{summary}"
            if url:
                result += f"\n\n*Quelle: [{url}]({url})*"
            return result.strip()
    except Exception:
        pass
    return str(content or "")


def _canonical_name(registry: ToolRegistry, name: str) -> str:
    tool = registry.get_tool(str(name or ""))
    return tool.name if tool is not None else str(name or "")


def _fallback_tool_calls(content: str, registry: ToolRegistry) -> List[Dict[str, Any]]:
    """Parse compatibility tool-call formats emitted by older/local models."""
    tool_calls: List[Dict[str, Any]] = []

    if "<tool_call>" in content:
        for match in XML_TOOL_CALL_RE.finditer(content):
            try:
                parsed = json.loads(match.group(1))
                if not isinstance(parsed, dict):
                    continue
                name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                if name and registry.get_tool(str(name)):
                    tool_calls.append({
                        "id": f"call_xml_{len(tool_calls)+1}",
                        "type": "function",
                        "function": {
                            "name": str(name),
                            "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                        },
                    })
            except (json.JSONDecodeError, TypeError):
                continue

    if not tool_calls and ("```json" in content or "```" in content):
        for match in JSON_CODE_BLOCK_RE.finditer(content):
            try:
                clean_json_str = re.sub(r"//.*", "", match.group(1))
                parsed = json.loads(clean_json_str)
                if not isinstance(parsed, dict):
                    continue
                name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                if name and registry.get_tool(str(name)):
                    tool_calls.append({
                        "id": f"call_json_{len(tool_calls)+1}",
                        "type": "function",
                        "function": {
                            "name": str(name),
                            "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                        },
                    })
            except (json.JSONDecodeError, TypeError):
                continue

    if not tool_calls:
        for match in RAW_JSON_TOOL_RE.finditer(content):
            name = match.group(1)
            if name and registry.get_tool(name):
                tool_calls.append({
                    "id": f"call_raw_{len(tool_calls)+1}",
                    "type": "function",
                    "function": {"name": name, "arguments": match.group(2)},
                })

    if not tool_calls and content.strip().startswith("{") and content.strip().endswith("}"):
        try:
            parsed = json.loads(content.strip())
            if isinstance(parsed, dict):
                name = parsed.get("name") or parsed.get("tool") or parsed.get("function")
                if name and registry.get_tool(str(name)):
                    tool_calls.append({
                        "id": "call_direct_1",
                        "type": "function",
                        "function": {
                            "name": str(name),
                            "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                        },
                    })
        except (json.JSONDecodeError, TypeError):
            pass

    return tool_calls[:MAX_TOOL_CALLS_PER_ITERATION]


def _decode_arguments(raw_args: Any) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    if isinstance(raw_args, dict):
        return raw_args, None
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            return None, f"Tool-Argumente sind kein gültiges JSON: {exc.msg}"
        if not isinstance(parsed, dict):
            return None, "Tool-Argumente müssen ein JSON-Objekt sein."
        return parsed, None
    return None, "Tool-Argumente müssen ein JSON-Objekt sein."


class AgentLoop:
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

        executed_records: List[ToolCallRecord] = []
        total_prompt_tok = 0
        total_comp_tok = 0
        last_assistant_content = ""

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

            if not tool_calls:
                final = format_tool_content_if_json(content)
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

            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                call_id = str(tool_call.get("id") or f"call_{len(executed_records)+1}")
                function = tool_call.get("function", {})
                function = function if isinstance(function, dict) else {}
                fn_name = str(function.get("name") or "")
                canonical = _canonical_name(self.registry, fn_name)
                args, argument_error = _decode_arguments(function.get("arguments", "{}"))
                record_args = args or {}

                if not fn_name:
                    tool_output: Any = {"error": "Tool-Aufruf enthält keinen Funktionsnamen."}
                elif argument_error:
                    tool_output = {"error": argument_error}
                elif canonical in disabled_set:
                    tool_output = {"error": f"Tool '{canonical}' ist für diese Flotte deaktiviert."}
                else:
                    tool_output = self.registry.execute_tool(fn_name, record_args, is_owner=is_owner)

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
