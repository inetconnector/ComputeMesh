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

        if "result" in data and ("expression" in data or "status" in data):
            expr = data.get("expression") or ""
            val = data.get("result")
            return f"Ergebnis: **{expr} = {val}**" if expr else f"Ergebnis: **{val}**"

        if "formatted_time" in data or "formatted_date" in data or "datetime_iso" in data or "current_time" in data or "local_time" in data:
            t = data.get("formatted_time") or data.get("current_time") or data.get("time") or ""
            d = data.get("formatted_date") or data.get("date") or ""
            tz = data.get("timezone", "Europe/Berlin")
            kw = data.get("calendar_week")
            res = f"Aktuelle Uhrzeit & Datum (**{tz}**):\n"
            if t:
                res += f"- **Uhrzeit:** {t}\n"
            if d:
                res += f"- **Datum:** {d}\n"
            if kw:
                res += f"- **Kalenderwoche:** KW {kw}\n"
            return res.strip()

        if "exchange_rate" in data or ("from" in data and "to" in data and "rate" in data):
            src = data.get("from", "").upper()
            dst = data.get("to", "").upper()
            rate = data.get("rate") or data.get("exchange_rate")
            amt = data.get("amount", 1)
            conv = data.get("converted_amount")
            if conv is not None:
                return f"Währungsumrechnung: **{amt} {src} = {conv:,.2f} {dst}** (Kurs: {rate})".strip()
            return f"Wechselkurs: **1 {src} = {rate} {dst}**".strip()
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


def detect_direct_tool_intent(text: str, registry: Optional[ToolRegistry] = None) -> Optional[tuple[str, dict[str, Any]]]:
    """Detects direct tool calling intent from user query with high precision."""
    cleaned = text.strip()
    
    # 1. Weather
    m_weather = re.search(
        r"(?:wie\s+(?:ist|wird)\s+das\s+wetter\s+(?:in|für|fuer)?\s*|wetter\s+(?:in|für|fuer)?\s*|weather\s+(?:in|for)?\s*|temperatur\s+(?:in|von)?\s*|regnet\s+es\s+in\s*)([a-zA-ZäöüÄÖÜß\s\-]+?)(?:\?|\.|$|\s+heute|\s+morgen|\s+aktuell|\s+am\s+wochenende)",
        cleaned,
        re.IGNORECASE
    )
    if m_weather:
        loc = m_weather.group(1).strip()
        loc = re.sub(r"^(?:den|dem|der|die|das)\s+", "", loc, flags=re.IGNORECASE).strip()
        if loc and len(loc) >= 2:
            return ("get_current_weather", {"location": loc})

    if re.search(r"(?:wie\s+(?:ist|wird)\s+das\s+wetter|wetterbericht|aktuelles\s+wetter|wetter\s+heute|wetter\s+morgen|wie\s+warm\s+ist\s+es|weather\s+today|wetter\?|\bwetter\b)", cleaned, re.IGNORECASE):
        return ("get_current_weather", {"location": "Veitshöchheim"})

    # 2. Market / Stock / Crypto Quotes
    if re.search(r"(?:bitcoin\s+preis|btc\s+kurs|bitcoin\s+kurs|btc\s+preis|\bbitcoin\b|\bbtc\b)", cleaned, re.IGNORECASE):
        return ("get_market_quote", {"symbol": "BTC"})
    if re.search(r"(?:ethereum\s+preis|eth\s+kurs|ethereum\s+kurs|eth\s+preis|\beth\b|\bethereum\b)", cleaned, re.IGNORECASE):
        return ("get_market_quote", {"symbol": "ETH"})
    if re.search(r"(?:solana\s+preis|sol\s+kurs|\bsolana\b)", cleaned, re.IGNORECASE):
        return ("get_market_quote", {"symbol": "SOL"})

    m_market = re.search(
        r"(?:aktienkurs\s+von\s+|aktienkurs\s+|aktie\s+|kurs\s+von\s+|preis\s+von\s+|wie\s+steht\s+(?:die\s+aktie\s+)?|stock\s+price\s+(?:of\s+)?|crypto\s+price\s+(?:of\s+)?)([a-zA-Z0-9\.\-\s]+?)(?:\?|\.|$|\s+aktuell)",
        cleaned,
        re.IGNORECASE
    )
    if m_market:
        sym = m_market.group(1).strip()
        if sym:
            return ("get_market_quote", {"symbol": sym})

    # 3. Time / Calendar / Holidays
    if re.search(r"(?:wie\s+spät\s+ist\s+es|wieviel\s+uhr\s+ist\s+es|aktuelle\s+uhrzeit|welcher\s+tag\s+ist\s+heute|welches\s+datum|wann\s+ist\s+ostern|feiertage\s+in|feiertage\s+\d{4}|current\s+time|what\s+time\s+is\s+it)", cleaned, re.IGNORECASE):
        return ("get_current_time_calendar", {})

    # 4. Math / Calculation
    m_calc = re.search(r"(?:berechne\s+|was\s+ist\s+)(\d+[\d\s\+\-\*\/\^\(\)\.\,\%]+)(?:\?|\.|$)", cleaned, re.IGNORECASE)
    if m_calc:
        expr = m_calc.group(1).strip()
        if any(op in expr for op in ("+", "-", "*", "/", "^", "%")):
            return ("calculate_math", {"expression": expr})

    # 5. News Feed
    if re.search(r"(?:aktuelle\s+nachrichten|nachrichten|news\s+heute|schlagzeilen|top\s+news|what's\s+the\s+news|latest\s+news)", cleaned, re.IGNORECASE):
        return ("get_news_feed", {"topic": "Deutschland & Welt"})

    # 6. Wikipedia
    m_wiki = re.search(r"(?:wer\s+war\s+|wer\s+ist\s+|was\s+ist\s+|wikipedia\s+(?:zu\s+|über\s+)?)([a-zA-Z0-9äöüÄÖÜß\s\-]+?)(?:\?|\.|$|\s+auf\s+wikipedia)", cleaned, re.IGNORECASE)
    if m_wiki:
        topic = m_wiki.group(1).strip()
        visual_words = ("bild", "foto", "screenshot", "grafik", "steht da", "erkenn", "lies", "dokument", "pdf", "sehen")
        is_visual = any(w in cleaned.lower() for w in visual_words)
        if len(topic) >= 3 and not is_visual and not topic.lower().startswith("das wetter") and not any(op in topic for op in ("+", "*", "/")):
            return ("get_wikipedia_summary", {"query": topic})

    # 7. Web Search
    m_search = re.search(r"(?:suche\s+(?:im\s+web\s+)?(?:nach\s+)?|search\s+(?:web\s+)?(?:for\s+)?|google\s+nach\s+)(.+?)(?:\?|\.|$)", cleaned, re.IGNORECASE)
    if m_search:
        q = m_search.group(1).strip()
        if q:
            return ("search_web", {"query": q})

    return None


REFUSAL_KEYWORDS = [
    "keine aktuellen",
    "keine echtzeitdaten",
    "kein echtzeitzugriff",
    "keine live-informationen",
    "kann nicht auf echtzeit",
    "kann nicht auf live",
    "habe keinen echtzeit",
    "keinen echtzeit-zugriff",
    "keine wetterdaten",
    "cannot provide real-time",
    "don't have access to real-time",
    "as an ai, i do not have access to live",
    "connection refused",
    "errno 111",
    "urlopen error",
    "standby",
    "offline",
    "failed to connect",
]


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

        # Ensure tools guidance is present in system instructions if tools are enabled
        if tools:
            has_system = any(m.get("role") == "system" for m in curr_messages)
            sys_guidance = (
                "Du bist ComputeMesh AI. Du hast vollen Zugriff auf die Live-Tools der ComputeMesh MCP Suite "
                "(z. B. get_current_weather für Wetter, get_market_quote für Börsen-/Kryptokurse, search_web für Websuche, "
                "get_wikipedia_summary für Wissen, calculate_math für Berechnungen, get_current_time_calendar für Uhrzeit/Datum). "
                "Nutze diese Live-Tools aktiv und beantworte Benutzerfragen zu Echtzeitdaten immer auf Basis der Tool-Ergebnisse."
            )
            if not has_system:
                curr_messages.insert(0, {"role": "system", "content": sys_guidance})

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
        if direct_intent and not any(m.get("role") == "tool" for m in curr_messages):
            fn_name, fn_args = direct_intent
            if fn_name not in disabled_set and self.registry.get_tool(fn_name):
                call_id = "call_direct_preflight_1"
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
                tool_res = self.registry.execute_tool(fn_name, fn_args, is_owner=is_owner)
                executed_records.append(ToolCallRecord(id=call_id, name=fn_name, arguments=fn_args, result=tool_res))
                curr_messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": fn_name,
                    "content": json.dumps(tool_res, ensure_ascii=False) if not isinstance(tool_res, str) else tool_res,
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
            if (not tool_calls or is_refusal) and direct_intent and iteration == 1:
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
