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
                    summary = article.get("summary", "")
                    source_text = f" *({source})*" if source else ""
                    if url and title:
                        result += f"{index}. [{title}]({url}){source_text}\n"
                    elif title:
                        result += f"{index}. **{title}**{source_text}\n"
                    if summary:
                        result += f"   {summary}\n\n"
                    else:
                        result += "\n"
            return result.strip()

        if "results" in data and isinstance(data.get("results"), list):
            q = data.get("query", "Websuche")
            results_list = data.get("results", [])
            if not results_list:
                return f"Für die Suchanfrage **'{q}'** wurden keine Live-Websuchergebnisse gefunden."
            res_str = f"Live-Websuchergebnisse für **'{q}'**:\n\n"
            for idx, r in enumerate(results_list[:5], 1):
                if not isinstance(r, dict):
                    continue
                title = r.get("title", "")
                url = r.get("url", "")
                snippet = r.get("snippet", "")
                if url and title:
                    res_str += f"{idx}. [{title}]({url})\n"
                elif title:
                    res_str += f"{idx}. **{title}**\n"
                if snippet:
                    res_str += f"   {snippet}\n\n"
            return res_str.strip()

        if "available_tools" in data and isinstance(data.get("available_tools"), list):
            tools_list = data.get("available_tools", [])
            res_str = "### 🛠️ Aktive ComputeMesh MCP-Module & Live-Tools\n\n"
            res_str += "Folgende Live-Werkzeuge sind auf diesem Cluster einsatzbereit:\n\n"
            for t in tools_list:
                name = t.get("name", "")
                desc = t.get("description", "")
                res_str += f"- **`{name}`**: {desc}\n"
            res_str += "\n*Alle Werkzeuge können direkt durch Fragen nach aktuellen Daten (Wetter, Suche, Kurse, News etc.) genutzt werden.*"
            return res_str.strip()

        if "city" in data and ("today" in data or "tomorrow" in data or "events" in data or "rubrics" in data):
            raw_city = str(data.get("city") or data.get("requestedCity") or "Veranstaltungen").strip()
            city = raw_city.title() if raw_city else "Veranstaltungen"
            notes_str = str(data.get("notes") or "").strip()
            sections = []

            rubric_icons = {
                "KONZERTE & LIVE-MUSIK": "🎸",
                "PARTY & CLUB": "🪩",
                "BÜHNE & THEATER": "🎭",
                "FESTE & FESTIVALS": "🎪",
                "KUNST & AUSSTELLUNGEN": "🎨",
                "SPORT & FITNESS": "⚽",
                "KURSE & WORKSHOPS": "🧠",
                "KINDER & FAMILIE": "🧸",
                "SONSTIGES": "📌",
            }

            for period_key in ("today", "tomorrow"):
                period = data.get(period_key)
                if not isinstance(period, dict):
                    continue
                label = period.get("dayLabel") or ("Heute" if period_key == "today" else "Morgen")
                date_iso = period.get("dateIso", "")
                rubrics = period.get("rubrics") or {}
                events = period.get("events") or []
                highlights = period.get("highlights") or []

                header = f"### 📅 {label}" + (f" ({date_iso})" if date_iso else "")
                period_blocks = []
                seen_titles: set[tuple[str, str]] = set()

                if rubrics:
                    preferred_order = [
                        "KONZERTE & LIVE-MUSIK",
                        "PARTY & CLUB",
                        "FESTE & FESTIVALS",
                        "BÜHNE & THEATER",
                        "KUNST & AUSSTELLUNGEN",
                        "SONSTIGES",
                        "KURSE & WORKSHOPS",
                        "SPORT & FITNESS",
                        "KINDER & FAMILIE",
                    ]
                    ordered_rubrics = [r for r in preferred_order if r in rubrics] + [r for r in rubrics if r not in preferred_order]

                    for rubric_name in ordered_rubrics:
                        r_events = rubrics[rubric_name]
                        if not r_events:
                            continue
                        icon = rubric_icons.get(rubric_name, "📌")
                        rubric_lines = [f"**{icon} {rubric_name.title()}:**"]
                        added_in_rubric = 0

                        for ev in r_events:
                            t = str(ev.get("title") or "").strip()
                            v = str(ev.get("venue") or "").strip()
                            st = str(ev.get("startTime") or "").strip()
                            desc = str(ev.get("description") or "").strip()
                            u = str(ev.get("url") or "").strip()
                            dist = ev.get("distanceKm")

                            key = (t.lower(), v.lower())
                            if key in seen_titles:
                                continue
                            seen_titles.add(key)

                            time_str = f" um {st} Uhr" if st and st != "None" else ""
                            dist_str = f" (~{dist} km)" if (dist and float(dist) > 2.0) else ""
                            loc_str = f" @ {v}{dist_str}" if v else (f" {dist_str}" if dist_str else "")
                            item_hdr = f"- **{t}**{loc_str}{time_str}"
                            if u and u.startswith("http"):
                                item_hdr += f" — [Info & Tickets]({u})"
                            rubric_lines.append(item_hdr)

                            if desc and len(desc) > 15 and not desc.startswith("http"):
                                clean_desc = re.sub(r"\s+", " ", desc).replace("\n", " ").strip()
                                if clean_desc.lower() != t.lower():
                                    short_desc = clean_desc[:120].strip() + ("..." if len(clean_desc) > 120 else "")
                                    rubric_lines.append(f"  *{short_desc}*")

                            added_in_rubric += 1
                            if added_in_rubric >= 6:
                                break

                        if added_in_rubric > 0:
                            period_blocks.append("\n".join(rubric_lines))

                elif events:
                    event_lines = []
                    for idx, ev in enumerate(events[:8], 1):
                        t = str(ev.get("title") or "").strip()
                        v = str(ev.get("venue") or "").strip()
                        st = str(ev.get("startTime") or "").strip()
                        desc = str(ev.get("description") or "").strip()
                        u = str(ev.get("url") or "").strip()
                        dist = ev.get("distanceKm")

                        key = (t.lower(), v.lower())
                        if key in seen_titles:
                            continue
                        seen_titles.add(key)

                        time_str = f" um {st} Uhr" if st and st != "None" else ""
                        dist_str = f" (~{dist} km)" if (dist and float(dist) > 2.0) else ""
                        loc_str = f" @ {v}{dist_str}" if v else (f" {dist_str}" if dist_str else "")
                        item_hdr = f"{idx}. **{t}**{loc_str}{time_str}"
                        if u and u.startswith("http"):
                            item_hdr += f" — [Info & Tickets]({u})"
                        event_lines.append(item_hdr)

                        if desc and len(desc) > 15 and not desc.startswith("http"):
                            clean_desc = re.sub(r"\s+", " ", desc).replace("\n", " ").strip()
                            if clean_desc.lower() != t.lower():
                                short_desc = clean_desc[:120].strip() + ("..." if len(clean_desc) > 120 else "")
                                event_lines.append(f"   *{short_desc}*")

                    if event_lines:
                        period_blocks.append("\n".join(event_lines))

                elif highlights:
                    hl_lines = [f"- {hl}" for hl in highlights[:6]]
                    period_blocks.append("\n".join(hl_lines))

                if period_blocks:
                    sections.append(header + "\n\n" + "\n\n".join(period_blocks))

            if sections:
                banner = f"## 🎟️ Live-Veranstaltungen & Konzerte in {city}\n\n"
                if notes_str:
                    banner += f"*ℹ️ {notes_str} (today.inetconnector.com)*\n\n"
                else:
                    banner += "*Echtzeit-Daten aus dem ComputeMesh Event-Index (today.inetconnector.com)*\n\n"
                return banner + "\n\n---\n\n".join(sections)

            # Fallback to Deep Cultural Research across subculture, live clubs, village gems and calendars
            try:
                from .builtin.web_search import deep_cultural_event_search
                deep_res = deep_cultural_event_search(city, max_results=8)
                rubrics_found = deep_res.get("rubrics", {})
                if rubrics_found:
                    res_str = f"## 🎟️ Aktuelle Veranstaltungen & Kultur-Highlights in {city}\n\n"
                    res_str += f"*Tiefenrecherche für den Raum {city} (Subkultur, Live-Bühnen, Regionalkultur & Kalender):*\n\n"
                    for badge_name, items in rubrics_found.items():
                        res_str += f"### {badge_name}\n\n"
                        for idx, r in enumerate(items, 1):
                            title = r.get("title", "")
                            url = r.get("url", "")
                            snippet = r.get("snippet", "")
                            if url and title:
                                res_str += f"{idx}. [{title}]({url})\n"
                            elif title:
                                res_str += f"{idx}. **{title}**\n"
                            if snippet:
                                clean_snip = re.sub(r"\s+", " ", snippet).strip()
                                res_str += f"   *{clean_snip}*\n\n"
                        res_str += "\n"
                    return res_str.strip()
            except Exception:
                pass

            return f"Für **{city}** konnten im aktuellen Zeitraum keine passenden Veranstaltungen gefunden werden."

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
    
    # 0. List Active MCP Modules & Tools
    if re.search(r"(?:welche\s+mcp|welche\s+tools|welche\s+module|aktive\s+tools|aktive\s+module|list\s+tools|available\s+tools|mcp\s+status|welche\s+funktionen\s+hast\s+du|was\s+kannst\s+du|welche\s+werkzeuge)", cleaned, re.IGNORECASE):
        return ("list_available_tools", {})

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

    # 5. News Feed & Headlines from Portals (Spiegel, Tagesschau, Heise, etc.)
    m_portal_news = re.search(
        r"(?:(?:die\s+|die\s+aktuellen\s+|aktuelle\s+)?(?:headlines|schlagzeilen|nachrichten|news|top\s+news|artikel)\s+(?:von\s+|aus\s+|auf\s+|bei\s+)?|was\s+gibt\s+es\s+neues\s+(?:bei\s+|auf\s+)?)\s*(spiegel(?:\s+online)?|tagesschau|heise(?:\s+online)?|golem(?:\s+online)?|zeit(?:\s+online)?|faz(?:\s+net)?|welt(?:\s+de)?|focus(?:\s+online)?|sueddeutsche)",
        cleaned,
        re.IGNORECASE
    )
    if m_portal_news:
        portal = m_portal_news.group(1).strip()
        return ("get_news_feed", {"topic": portal})

    if any(p in cleaned.lower() for p in ("spiegel", "tagesschau", "heise", "zeit", "faz", "welt", "focus", "sueddeutsche")) and any(w in cleaned.lower() for w in ("headline", "schlagzeil", "nachricht", "news", "aktuell", "heute", "artikel", "titel")):
        for p_name in ("spiegel", "tagesschau", "heise", "zeit", "faz", "welt", "focus", "sueddeutsche"):
            if p_name in cleaned.lower():
                return ("get_news_feed", {"topic": p_name})
        return ("get_news_feed", {"topic": "spiegel online"})

    # 6. Events, Concerts, Subculture & Regional Discovery (Worldwide & Europe with typo tolerance)
    if re.search(r"(?:kon[tz]+ert[a-z]*|con[cz]i?ert[a-z]*|veranstalt[a-z]*|verantstalt[a-z]*|events?|part[yi]e?s?|gigs?|festivals?|live[\s\-_]?musik|live[\s\-_]?music|was\s+geht|things\s+to\s+do|what\s+to\s+do|what'?s\s+(?:on|happening|going\s+on)|what\s+is\s+on|live[\s\-_]?bands?|bands\s+live|ausgehen|kulturprogramm|spielplan|clubbing|disco|disko|nightlife|klapperfeld|subkultur|kulturzentrum|off-space|b\u00fcrgerhaus|scheune|dorfgemeinschaftshaus|kleinkunst|freiraum|autonomes?\s+zentrum|tiers-lieux|friche|squat|grassroots)", cleaned, re.IGNORECASE):
        city_aliases = {
            "wue": "Würzburg",
            "wü": "Würzburg",
            "wuerzburg": "Würzburg",
            "würzburg": "Würzburg",
            "würzburger": "Würzburg",
            "münchen": "München",
            "munich": "München",
            "muc": "München",
            "münchner": "München",
            "nürnberg": "Nürnberg",
            "nuernberg": "Nürnberg",
            "nürnberger": "Nürnberg",
            "schweinfurt": "Schweinfurt",
            "veitshöchheim": "Veitshöchheim",
            "veitshoechheim": "Veitshöchheim",
            "frankfurt": "Frankfurt am Main",
            "ffm": "Frankfurt am Main",
            "berlin": "Berlin",
            "hamburg": "Hamburg",
            "stuttgart": "Stuttgart",
            "köln": "Köln",
            "koeln": "Köln",
            "cologne": "Köln",
            "dresden": "Dresden",
            "leipzig": "Leipzig",
            "augsburg": "Augsburg",
            "regensburg": "Regensburg",
            "bamberg": "Bamberg",
            "erlangen": "Erlangen",
            "kitzingen": "Kitzingen",
            "aschaffenburg": "Aschaffenburg",
            "lohr": "Lohr",
            "karlstadt": "Karlstadt",
            "ochsenfurt": "Ochsenfurt",
            "marktheidenfeld": "Marktheidenfeld",
            "bad-kissingen": "Bad Kissingen",
            "düsseldorf": "Düsseldorf",
            "duesseldorf": "Düsseldorf",
            "dortmund": "Dortmund",
            "essen": "Essen",
            "bremen": "Bremen",
            "hannover": "Hannover",
            "duisburg": "Duisburg",
            "bochum": "Bochum",
            "wuppertal": "Wuppertal",
            "bielefeld": "Bielefeld",
            "bonn": "Bonn",
            "münster": "Münster",
            "karlsruhe": "Karlsruhe",
            "mannheim": "Mannheim",
            "wiesbaden": "Wiesbaden",
            "gelsenkirchen": "Gelsenkirchen",
            "mönchengladbach": "Mönchengladbach",
            "braunschweig": "Braunschweig",
            "chemnitz": "Chemnitz",
            "kiel": "Kiel",
            "aachen": "Aachen",
            "halle": "Halle (Saale)",
            "magdeburg": "Magdeburg",
            "freiburg": "Freiburg im Breisgau",
            "krefeld": "Krefeld",
            "mainz": "Mainz",
            "lübeck": "Lübeck",
            "erfurt": "Erfurt",
            "oberhausen": "Oberhausen",
            "rostock": "Rostock",
            "kassel": "Kassel",
            "potsdam": "Potsdam",
            "saarbrücken": "Saarbrücken",
            "heidelberg": "Heidelberg",
            "darmstadt": "Darmstadt",
            "ulm": "Ulm",
            "wien": "Wien",
            "vienna": "Wien",
            "zürich": "Zürich",
            "zurich": "Zürich",
            "zuerich": "Zürich",
            "salzburg": "Salzburg",
            "innsbruck": "Innsbruck",
            "graz": "Graz",
            "linz": "Linz",
            "basel": "Basel",
            "bern": "Bern",
            "genf": "Genf",
            "geneva": "Genf",
            "lausanne": "Lausanne",
            "london": "London",
            "manchester": "Manchester",
            "birmingham": "Birmingham",
            "liverpool": "Liverpool",
            "leeds": "Leeds",
            "glasgow": "Glasgow",
            "edinburgh": "Edinburgh",
            "bristol": "Bristol",
            "cardiff": "Cardiff",
            "belfast": "Belfast",
            "paris": "Paris",
            "lyon": "Lyon",
            "marseille": "Marseille",
            "bordeaux": "Bordeaux",
            "toulouse": "Toulouse",
            "nice": "Nizza",
            "nizza": "Nizza",
            "nantes": "Nantes",
            "strasbourg": "Straßburg",
            "straßburg": "Straßburg",
            "lille": "Lille",
            "madrid": "Madrid",
            "barcelona": "Barcelona",
            "valencia": "Valencia",
            "sevilla": "Sevilla",
            "seville": "Sevilla",
            "bilbao": "Bilbao",
            "malaga": "Málaga",
            "zaragoza": "Zaragoza",
            "rom": "Rom",
            "rome": "Rom",
            "roma": "Rom",
            "milan": "Mailand",
            "mailand": "Mailand",
            "milano": "Mailand",
            "napoli": "Neapel",
            "neapel": "Neapel",
            "torino": "Turin",
            "turin": "Turin",
            "bologna": "Bologna",
            "firenze": "Florenz",
            "florenz": "Florenz",
            "venezia": "Venedig",
            "venedig": "Venedig",
            "amsterdam": "Amsterdam",
            "rotterdam": "Rotterdam",
            "den-haag": "Den Haag",
            "utrecht": "Utrecht",
            "eindhoven": "Eindhoven",
            "brüssel": "Brüssel",
            "brussels": "Brüssel",
            "bruxelles": "Brüssel",
            "antwerpen": "Antwerpen",
            "gent": "Gent",
            "lüttich": "Lüttich",
            "liege": "Lüttich",
            "dublin": "Dublin",
            "prag": "Prag",
            "prague": "Prag",
            "praha": "Prag",
            "brno": "Brünn",
            "warschau": "Warschau",
            "warsaw": "Warschau",
            "warszawa": "Warschau",
            "krakow": "Krakau",
            "krakau": "Krakau",
            "wroclaw": "Breslau",
            "breslau": "Breslau",
            "poznan": "Posen",
            "gdansk": "Danzig",
            "budapest": "Budapest",
            "lissabon": "Lissabon",
            "lisbon": "Lissabon",
            "lisboa": "Lissabon",
            "porto": "Porto",
            "athen": "Athen",
            "athens": "Athen",
            "thessaloniki": "Thessaloniki",
            "stockholm": "Stockholm",
            "gothenburg": "Göteborg",
            "göteborg": "Göteborg",
            "malmo": "Malmö",
            "malmö": "Malmö",
            "oslo": "Oslo",
            "bergen": "Bergen",
            "kopenhagen": "Kopenhagen",
            "copenhagen": "Kopenhagen",
            "aarhus": "Aarhus",
            "helsinki": "Helsinki",
            "tallinn": "Tallinn",
            "riga": "Riga",
            "vilnius": "Vilnius",
            "zagreb": "Zagreb",
            "split": "Split",
            "belgrad": "Belgrad",
            "belgrade": "Belgrad",
            "bukarest": "Bukarest",
            "bucharest": "Bukarest",
            "sofia": "Sofia",
            "tokio": "Tokio",
            "tokyo": "Tokio",
            "osaka": "Osaka",
            "kyoto": "Kyoto",
            "seoul": "Seoul",
            "peking": "Peking",
            "beijing": "Peking",
            "shanghai": "Shanghai",
            "hongkong": "Hongkong",
            "singapur": "Singapur",
            "singapore": "Singapur",
            "bangkok": "Bangkok",
            "mumbai": "Mumbai",
            "delhi": "Delhi",
            "new-delhi": "Neu-Delhi",
            "sydney": "Sydney",
            "melbourne": "Melbourne",
            "brisbane": "Brisbane",
            "auckland": "Auckland",
            "new-york": "New York",
            "new york": "New York",
            "nyc": "New York",
            "los-angeles": "Los Angeles",
            "los angeles": "Los Angeles",
            "chicago": "Chicago",
            "san-francisco": "San Francisco",
            "san francisco": "San Francisco",
            "toronto": "Toronto",
            "montreal": "Montreal",
            "vancouver": "Vancouver",
            "mexiko-stadt": "Mexiko-Stadt",
            "mexico-city": "Mexiko-Stadt",
            "buenos-aires": "Buenos Aires",
            "sao-paulo": "São Paulo",
            "rio": "Rio de Janeiro",
            "rio-de-janeiro": "Rio de Janeiro",
            "kairo": "Kairo",
            "cairo": "Kairo",
            "kapstadt": "Kapstadt",
            "cape-town": "Kapstadt",
            "johannesburg": "Johannesburg",
            "istanbul": "Istanbul",
            "dubai": "Dubai",
        }

        city = "Würzburg"
        found_city = None
        for token in re.findall(r"[a-zA-ZäöüÄÖÜß\-]+", cleaned.lower()):
            if token in city_aliases:
                found_city = city_aliases[token]
                break

        if found_city:
            city = found_city
        else:
            m_city = re.search(
                r"(?:in|at|near|around|à|a|en|para|für|fuer|im\s+raum|bei|aus)\s+([a-zA-ZäöüÄÖÜß\s\-]+?)(?:\?|\.|$|\s+heute|\s+morgen|\s+am\s+wochenende|\s+dieses\s+wochenende|\s+today|\s+tonight|\s+this\s+weekend)",
                cleaned,
                re.IGNORECASE
            )
            if m_city:
                extracted = m_city.group(1).strip()
                extracted = re.sub(r"^(?:den|dem|der|die|das|the|le|la|les|el|los|las)\s+", "", extracted, flags=re.IGNORECASE).strip()
                if extracted and len(extracted) >= 2 and extracted.lower() not in ("wochenende", "samstag", "sonntag", "freitag", "diesem", "dieser", "der", "dem", "einem", "weekend", "today", "tonight"):
                    city = extracted

        categories = []
        if re.search(r"(?:kon[tz]+ert|con[cz]i?ert|live[\s\-_]?musik|live[\s\-_]?music|live[\s\-_]?band|gigs?|band)", cleaned, re.IGNORECASE):
            categories.append("concert")
        elif re.search(r"(?:part[yi]e?s?|club|feiern|disko|disco|clubbing|nightlife)", cleaned, re.IGNORECASE):
            categories.append("party_club")
        elif re.search(r"(?:theater|schauspiel|bühne|stage|comedy|kabarett)", cleaned, re.IGNORECASE):
            categories.append("theater_stage")

        day_scope = "today_tomorrow"
        if re.search(r"\b(?:heute|today|heutige|tonight)\b", cleaned, re.IGNORECASE):
            day_scope = "today"

        # Check if radius was explicitly requested in text (e.g. "im Umkreis von 50 km" or "50km")
        radius_km = 50.0
        m_rad = re.search(r"(?:umkreis\s+(?:von\s+)?|radius\s+(?:von\s+)?|in\s+(\d+)\s*km)(\d+)?\s*km?", cleaned, re.IGNORECASE)
        if m_rad:
            try:
                rad_val = float(m_rad.group(1) or m_rad.group(2) or 50.0)
                if 1 <= rad_val <= 300:
                    radius_km = rad_val
            except (ValueError, TypeError):
                pass

        return ("search_events", {
            "city": city,
            "radius_km": radius_km,
            "categories": categories,
            "day_scope": day_scope,
        })

    # 7. Wikipedia
    m_wiki = re.search(r"(?:wer\s+war\s+|wer\s+ist\s+|was\s+ist\s+|wikipedia\s+(?:zu\s+|über\s+)?)([a-zA-Z0-9äöüÄÖÜß\s\-]+?)(?:\?|\.|$|\s+auf\s+wikipedia)", cleaned, re.IGNORECASE)
    if m_wiki:
        topic = m_wiki.group(1).strip()
        visual_words = ("bild", "foto", "screenshot", "grafik", "steht da", "erkenn", "lies", "dokument", "pdf", "sehen")
        is_visual = any(w in cleaned.lower() for w in visual_words)
        if len(topic) >= 3 and not is_visual and not topic.lower().startswith("das wetter") and not any(op in topic for op in ("+", "*", "/")):
            return ("get_wikipedia_summary", {"query": topic})

    # 7. Web Search & Google Queries
    m_search = re.search(
        r"(?:google\s+(?:nach\s+|mal\s+)?|suche\s+(?:im\s+web\s+)?(?:nach\s+)?|search\s+(?:web\s+)?(?:for\s+)?|finde\s+(?:im\s+web\s+)?|web\s*suche\s+(?:nach\s+)?)(.+?)(?:\?|\.|$)",
        cleaned,
        re.IGNORECASE
    )
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
                tool_res = self.registry.execute_tool(fn_name, fn_args, is_owner=is_owner)
                executed_records.append(ToolCallRecord(id=call_id, name=fn_name, arguments=fn_args, result=tool_res))

                formatted_direct = format_tool_content_if_json(
                    tool_res if isinstance(tool_res, str) else json.dumps(tool_res, ensure_ascii=False)
                )
                if formatted_direct and not (formatted_direct.startswith("{") and formatted_direct.endswith("}")):
                    curr_messages.append({"role": "assistant", "content": formatted_direct})
                    return AgentExecutionResult(
                        final_content=formatted_direct,
                        messages=curr_messages,
                        tool_calls_executed=executed_records,
                        iterations=1,
                        model=model,
                        prompt_tokens=30,
                        completion_tokens=50,
                        total_tokens=80,
                    )

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
