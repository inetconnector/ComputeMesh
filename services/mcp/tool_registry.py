# SPDX-License-Identifier: Apache-2.0
"""
Central Tool Registry for ComputeMesh MCP Subsystem.
Formats tools for OpenAI API (`tools` / function calling schema) and handles execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import MCPConfig, get_mcp_config
from .builtin.web_search import execute_web_search
from .builtin.finance_market import execute_finance_quote
from .builtin.web_fetch import execute_web_fetch
from .builtin.news_feed import execute_get_news
from .builtin.weather import execute_get_weather
from .builtin.python_calc import run_python_calc
from .builtin.wikipedia import get_wikipedia_summary
from .builtin.time_calendar import get_time_and_calendar
from .builtin.currency import convert_currency
from .builtin.geo_routing import get_distance_route
from .builtin.network_tools import lookup_network_host
from .builtin.system_tools import execute_system_info


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]
    owner_only: bool = False
    source: str = "builtin"

    def to_openai_dict(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, config: Optional[MCPConfig] = None):
        self.config = config or get_mcp_config()
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        owner_only: bool = False,
        source: str = "builtin",
    ) -> None:
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            owner_only=owner_only,
            source=source,
        )

    def unregister_tool(self, name: str) -> None:
        if name in self._tools:
            del self._tools[name]

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self, is_owner: bool = True) -> List[ToolDefinition]:
        if is_owner:
            return list(self._tools.values())
        return [t for t in self._tools.values() if not t.owner_only]

    def get_openai_tools(self, is_owner: bool = True) -> List[Dict[str, Any]]:
        return [t.to_openai_dict() for t in self.list_tools(is_owner=is_owner)]

    def execute_tool(self, name: str, arguments: Dict[str, Any], is_owner: bool = True) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' nicht gefunden"}

        if tool.owner_only and not is_owner:
            return {"error": f"Tool '{name}' erfordert Authentifizierung mit Owner Key"}

        try:
            return tool.handler(**arguments)
        except TypeError as te:
            # If arguments structure differs slightly, attempt with raw dictionary or fallback
            try:
                return tool.handler(arguments)
            except Exception:
                return {"error": f"Ungültige Tool-Parameter für '{name}': {str(te)}"}
        except Exception as e:
            return {"error": f"Fehler bei Ausführung von Tool '{name}': {str(e)}"}

    def _register_default_tools(self) -> None:
        # 1. Live Web Search Tool
        if self.config.web_search_enabled:
            self.register_tool(
                name="search_web",
                description="Sucht live im Web nach aktuellen Informationen, Nachrichten, Dokumentationen oder Fakten.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Die Suchanfrage für die Websuche.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximale Anzahl an Suchergebnissen (1-10). Standard: 5.",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
                handler=execute_web_search,
                owner_only=False,
                source="builtin_web",
            )

        # 2. Financial & Stock Quotes Tool
        if self.config.finance_enabled:
            self.register_tool(
                name="get_market_quote",
                description="Liefert aktuelle Live-Börsenkurse, Aktienpreise, Indizes (DAX, S&P500), Rohstoffe (Gold, Öl) und Kryptowährungen (BTC, ETH, SOL).",
                parameters={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Das Tickersymbol (z. B. AAPL, NVDA, SAP.DE, BTC, ETH, DAX, GOLD).",
                        },
                    },
                    "required": ["symbol"],
                },
                handler=execute_finance_quote,
                owner_only=False,
                source="builtin_finance",
            )

        # 3. Web Page Content Fetcher
        if self.config.web_fetch_enabled:
            self.register_tool(
                name="fetch_web_content",
                description="Lädt den vollständigen Textinhalt einer Webseite oder eines Online-Artikels anhand einer URL herunter.",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Die vollständige URL der Webseite (z. B. https://example.com/artikel).",
                        },
                    },
                    "required": ["url"],
                },
                handler=execute_web_fetch,
                owner_only=False,
                source="builtin_web",
            )

        # 4. Live News & Current Events Feed
        self.register_tool(
            name="get_live_news",
            description="Liefert aktuelle Live-Nachrichten und Schlagzeilen zu Themen wie 'tech', 'business', 'crypto', 'germany', 'world' oder beliebigen Suchbegriffen.",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Thema oder Suchbegriff (z. B. 'tech', 'business', 'crypto', 'germany', 'world' oder 'Nvidia'). Standard: 'general'.",
                        "default": "general",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximale Anzahl an Nachrichtenartikeln (1-10). Standard: 5.",
                        "default": 5,
                    },
                },
            },
            handler=execute_get_news,
            owner_only=False,
            source="builtin_news",
        )

        # 5. Live Weather Tool
        self.register_tool(
            name="get_current_weather",
            description="Liefert aktuelle Live-Wetterdaten, Temperatur, Luftfeuchtigkeit, Windgeschwindigkeit und Wetterbedingungen für jeden Ort oder jede Stadt weltweit (z. B. 'Veitshöchheim', 'Würzburg', 'Berlin').",
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Der Name der Stadt oder des Ortes (z. B. 'Veitshöchheim', 'Würzburg', 'München', 'Berlin').",
                    },
                },
                "required": ["location"],
            },
            handler=execute_get_weather,
            owner_only=False,
            source="builtin_weather",
        )

        # 6. Safe Python Math Evaluator
        self.register_tool(
            name="calculate_math",
            description="Führt präzise mathematische Berechnungen, Finanzformeln, Zinsrechnungen, Statistiken oder Algorithmen in einer isolierten Python-Sandbox aus.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Der mathematische Ausdruck oder Python-Code (z. B. '150000 * (0.038 / 12) / (1 - (1 + 0.038 / 12) ** -180)' oder 'math.sqrt(42)').",
                    },
                },
                "required": ["expression"],
            },
            handler=run_python_calc,
            owner_only=False,
            source="builtin_math",
        )

        # 7. Wikipedia Reference Tool
        self.register_tool(
            name="get_wikipedia_summary",
            description="Liefert fundierte lexikalische Zusammenfassungen, Definitionen, historische Fakten und Biografien direkt aus Wikipedia.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Das Thema, der Begriff oder die Person (z. B. 'Veitshöchheim', 'Quantencomputer', 'Alan Turing').",
                    },
                    "language": {
                        "type": "string",
                        "description": "Sprachcode ('de', 'en', 'fr', 'es'). Standard: 'de'.",
                        "default": "de",
                    },
                },
                "required": ["query"],
            },
            handler=get_wikipedia_summary,
            owner_only=False,
            source="builtin_wiki",
        )

        # 8. World Time, Calendar & German Holidays
        self.register_tool(
            name="get_time_and_calendar",
            description="Liefert die exakte aktuelle Uhrzeit, Zeitzonen-Umrechnung, Kalenderwoche, Schaltjahr-Prüfung und gesetzliche Feiertage (z. B. für Bayern BY).",
            parameters={
                "type": "object",
                "properties": {
                    "timezone_name": {
                        "type": "string",
                        "description": "Name der Zeitzone oder Stadt (z. B. 'Europe/Berlin', 'Tokyo', 'New York', 'London'). Standard: 'Europe/Berlin'.",
                        "default": "Europe/Berlin",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "Optionales Zieldatum im Format 'YYYY-MM-DD' oder 'DD.MM.YYYY' zur Berechnung der Tage bis zum Datum.",
                    },
                    "state": {
                        "type": "string",
                        "description": "Bundesland-Kürzel für Feiertage (z. B. 'BY' für Bayern, 'BW', 'NW'). Standard: 'BY'.",
                        "default": "BY",
                    },
                },
            },
            handler=get_time_and_calendar,
            owner_only=False,
            source="builtin_time",
        )

        # 9. Currency & Crypto Converter
        self.register_tool(
            name="convert_currency",
            description="Rechnet Geldbeträge live zwischen weltweiten Währungen (EUR, USD, GBP, CHF, JPY etc.) oder Kryptowährungen (BTC, ETH, SOL) um.",
            parameters={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Der umzurechnende Betrag (z. B. 100).",
                        "default": 1.0,
                    },
                    "from_currency": {
                        "type": "string",
                        "description": "Ausgangswährung (z. B. 'EUR', 'USD', 'BTC'). Standard: 'EUR'.",
                        "default": "EUR",
                    },
                    "to_currency": {
                        "type": "string",
                        "description": "Zielwährung (z. B. 'USD', 'EUR', 'CHF'). Standard: 'USD'.",
                        "default": "USD",
                    },
                },
                "required": ["amount", "from_currency", "to_currency"],
            },
            handler=convert_currency,
            owner_only=False,
            source="builtin_currency",
        )

        # 10. Geographic Distance & Route Tool
        self.register_tool(
            name="get_distance_route",
            description="Berechnet die exakte Entfernung (Luftlinie & Fahrtstrecke), Himmelsrichtung, Geokoordinaten und geschätzte Fahrzeit zwischen zwei Orten weltweit.",
            parameters={
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "Startort oder Startadresse (z. B. 'Veitshöchheim' oder 'Würzburg').",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Zielort oder Zieladresse (z. B. 'München' oder 'Frankfurt am Main').",
                    },
                },
                "required": ["origin", "destination"],
            },
            handler=get_distance_route,
            owner_only=False,
            source="builtin_geo",
        )

        # 11. Safe Network & Host Diagnostics (Owner Key only)
        self.register_tool(
            name="lookup_network_host",
            description="Führt sichere Netzwerkdiagnosen für eine öffentliche Domain aus (DNS-Einträge, HTTP/HTTPS-Status & Latenz, SSL-Zertifikatslaufzeit).",
            parameters={
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Der öffentliche Hostname oder die Domain (z. B. 'inetconnector.com' oder 'github.com').",
                    },
                    "check_type": {
                        "type": "string",
                        "description": "Art der Diagnose: 'all' (DNS, HTTP & SSL), 'dns_only', 'http', 'ssl'. Standard: 'all'.",
                        "default": "all",
                    },
                },
                "required": ["host"],
            },
            handler=lookup_network_host,
            owner_only=True,
            source="builtin_network",
        )

        # 12. Safe System Info Tool (Owner only)
        if self.config.system_tools_enabled:
            self.register_tool(
                name="get_system_info",
                description="Liefert Host- und Systeminformationen des Compute-Knotens (Betriebssystem, CPU-Kerne, Server-Zeit).",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=execute_system_info,
                owner_only=True,
                source="builtin_system",
            )
