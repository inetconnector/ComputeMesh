# SPDX-License-Identifier: Apache-2.0
"""Central Tool Registry for the ComputeMesh MCP subsystem.

The registry exposes built-in live-data tools in OpenAI function-calling format,
resolves backwards-compatible aliases, enforces owner-only tools, and performs a
small fail-closed validation pass for schemas that set ``additionalProperties``
to ``False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .config import MCPConfig, get_mcp_config
from .builtin.arxiv_research import search_arxiv_papers
from .builtin.chemical_data import lookup_chemical_compound
from .builtin.company_lookup import lookup_company
from .builtin.country_data import lookup_country_data
from .builtin.currency import convert_currency
from .builtin.dictionary_lookup import lookup_word_definition
from .builtin.earthquake_feed import get_recent_earthquakes
from .builtin.events import search_events
from .builtin.finance_market import execute_finance_quote
from .builtin.food_products import lookup_food_product
from .builtin.geo_routing import get_distance_route
from .builtin.network_tools import lookup_network_host
from .builtin.news_feed import execute_get_news
from .builtin.package_registry import lookup_software_package
from .builtin.places import search_places
from .builtin.python_calc import run_python_calc
from .builtin.sports_data import get_sports_data
from .builtin.system_tools import execute_system_info
from .builtin.time_calendar import get_time_and_calendar
from .builtin.train_transit import lookup_train_schedule
from .builtin.weather import execute_get_weather
from .builtin.weather_forecast import get_weather_forecast
from .builtin.web_fetch import execute_web_fetch
from .builtin.web_search import execute_web_search
from .builtin.wikipedia import get_wikipedia_summary
from .builtin.world_bank import get_world_bank_stats


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


TOOL_ALIASES: Dict[str, str] = {
    "get_weather": "get_current_weather",
    "weather": "get_current_weather",
    "current_weather": "get_current_weather",
    "weather_forecast": "get_weather_forecast",
    "forecast": "get_weather_forecast",
    "web_search": "search_web",
    "brave_web_search": "search_web",
    "search": "search_web",
    "web_search_query": "search_web",
    "stock_quote": "get_market_quote",
    "get_stock_quote": "get_market_quote",
    "crypto_price": "get_market_quote",
    "market_quote": "get_market_quote",
    "calculator": "calculate_math",
    "calc": "calculate_math",
    "math": "calculate_math",
    "calculate": "calculate_math",
    "wikipedia": "get_wikipedia_summary",
    "get_wikipedia": "get_wikipedia_summary",
    "dns": "lookup_network_host",
    "dns_lookup": "lookup_network_host",
    "get_top_news": "get_live_news",
    "get_news": "get_live_news",
    "get_news_feed": "get_live_news",
    "news": "get_live_news",
    "news_feed": "get_live_news",
    "events": "search_events",
    "event_search": "search_events",
    "places": "search_places",
    "place_search": "search_places",
    "sports": "get_sports_data",
    "company": "lookup_company",
    "company_lookup": "lookup_company",
    "get_current_time_calendar": "get_time_and_calendar",
    "get_current_time": "get_time_and_calendar",
    "get_time": "get_time_and_calendar",
    "current_time": "get_time_and_calendar",
    "time": "get_time_and_calendar",
    "uhrzeit": "get_time_and_calendar",
    "bitcoin_price": "get_market_quote",
    "btc_price": "get_market_quote",
}


def _matches_type(value: Any, expected: Any) -> bool:
    expected_types = expected if isinstance(expected, list) else [expected]
    for item in expected_types:
        if item == "null" and value is None:
            return True
        if item == "string" and isinstance(value, str):
            return True
        if item == "boolean" and isinstance(value, bool):
            return True
        if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if item == "array" and isinstance(value, list):
            return True
        if item == "object" and isinstance(value, dict):
            return True
    return False


def _validate_strict_arguments(schema: Dict[str, Any], arguments: Any) -> Optional[str]:
    """Validate the subset needed by strict built-in schemas without a dependency."""
    if not isinstance(arguments, dict):
        return "Tool-Parameter müssen ein JSON-Objekt sein."
    if schema.get("additionalProperties") is not False:
        return None

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        return f"Unbekannte Tool-Parameter: {', '.join(unknown)}"

    missing = [name for name in schema.get("required", []) if name not in arguments]
    if missing:
        return f"Fehlende Pflichtparameter: {', '.join(missing)}"

    for name, value in arguments.items():
        spec = properties.get(name)
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        if expected is not None and not _matches_type(value, expected):
            return f"Parameter '{name}' hat einen ungültigen Typ."
        if "enum" in spec and value not in spec["enum"]:
            return f"Parameter '{name}' hat einen ungültigen Wert."
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                return f"Parameter '{name}' liegt unter dem Minimum {spec['minimum']}."
            if "maximum" in spec and value > spec["maximum"]:
                return f"Parameter '{name}' liegt über dem Maximum {spec['maximum']}."
    return None


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
        self._tools.pop(name, None)

    def _resolve_tool_name(self, name: str) -> str:
        if not name:
            return ""
        if name in self._tools:
            return name
        if name in TOOL_ALIASES:
            return TOOL_ALIASES[name]

        lower_name = name.lower().replace("-", "_")
        if lower_name in self._tools:
            return lower_name
        if lower_name in TOOL_ALIASES:
            return TOOL_ALIASES[lower_name]

        if "forecast" in lower_name or "vorhersage" in lower_name:
            return "get_weather_forecast"
        if any(k in lower_name for k in ("weather", "wetter", "temperature", "klima", "regen", "sonne")):
            return "get_current_weather"
        if any(k in lower_name for k in ("event", "veranstaltung", "concert", "konzert")):
            return "search_events"
        if any(k in lower_name for k in ("place", "poi", "restaurant", "hotel", "geschäft", "business_near")):
            return "search_places"
        if any(k in lower_name for k in ("sport", "score", "spielplan", "fixture", "league")):
            return "get_sports_data"
        if any(k in lower_name for k in ("company", "unternehmen", "firma", "legal_entity", "lei")):
            return "lookup_company"
        if any(k in lower_name for k in ("search", "google", "bing", "brave", "find", "suchen", "web_query")):
            return "search_web"
        if any(k in lower_name for k in ("stock", "crypto", "quote", "aktie", "kurs", "krypto", "bitcoin", "eth", "market", "ticker")):
            return "get_market_quote"
        if any(k in lower_name for k in ("calc", "math", "rechen", "eval", "berechne", "formel")):
            return "calculate_math"
        if any(k in lower_name for k in ("wiki", "wikipedia", "lexikon", "enzyklop", "biografie", "definition")):
            return "get_wikipedia_summary"
        if any(k in lower_name for k in ("dns", "nslookup", "domain", "resolve", "ip_lookup")):
            return "lookup_network_host"
        if any(k in lower_name for k in ("news", "nachricht", "schlagzeile", "zeitung")):
            return "get_live_news"
        return name

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        resolved = self._resolve_tool_name(name)
        return self._tools.get(resolved) or self._tools.get(name)

    def list_tools(self, is_owner: bool = True) -> List[ToolDefinition]:
        if is_owner:
            return list(self._tools.values())
        return [tool for tool in self._tools.values() if not tool.owner_only]

    def get_openai_tools(self, is_owner: bool = True) -> List[Dict[str, Any]]:
        return [tool.to_openai_dict() for tool in self.list_tools(is_owner=is_owner)]

    def execute_tool(self, name: str, arguments: Dict[str, Any], is_owner: bool = True) -> Any:
        resolved = self._resolve_tool_name(name)
        tool = self._tools.get(resolved) or self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' nicht gefunden"}
        if tool.owner_only and not is_owner:
            return {"error": f"Tool '{name}' erfordert Authentifizierung mit Owner Key"}

        validation_error = _validate_strict_arguments(tool.parameters, arguments)
        if validation_error:
            return {"error": f"Ungültige Tool-Parameter für '{name}': {validation_error}"}
        if not isinstance(arguments, dict):
            return {"error": f"Ungültige Tool-Parameter für '{name}': JSON-Objekt erwartet"}

        try:
            return tool.handler(**arguments)
        except TypeError as exc:
            return {"error": f"Ungültige Tool-Parameter für '{name}': {exc}"}
        except Exception as exc:
            return {"error": f"Fehler bei Ausführung von Tool '{name}': {exc}"}

    def _register_default_tools(self) -> None:
        def schema(properties: Dict[str, Any], required: List[str] | None = None, *, strict: bool = False) -> Dict[str, Any]:
            value: Dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                value["required"] = required
            if strict:
                value["additionalProperties"] = False
            return value

        if self.config.web_search_enabled:
            self.register_tool(
                "search_web",
                "Sucht live im Web nach aktuellen Informationen, Nachrichten, Dokumentationen oder Fakten.",
                schema({
                    "query": {"type": "string", "description": "Suchanfrage."},
                    "max_results": {"type": "integer", "description": "Maximal 1-10 Ergebnisse.", "default": 5},
                }, ["query"]),
                execute_web_search,
                source="builtin_web",
            )

        if self.config.finance_enabled:
            self.register_tool(
                "get_market_quote",
                "Liefert aktuelle Kurse für Aktien, Indizes, Rohstoffe und Kryptowährungen.",
                schema({"symbol": {"type": "string", "description": "Ticker, z. B. AAPL, SAP.DE, BTC, DAX."}}, ["symbol"]),
                execute_finance_quote,
                source="builtin_finance",
            )

        if self.config.web_fetch_enabled:
            self.register_tool(
                "fetch_web_content",
                "Lädt Textinhalt einer Webseite anhand einer URL.",
                schema({"url": {"type": "string", "description": "Vollständige https/http URL."}}, ["url"]),
                execute_web_fetch,
                source="builtin_web",
            )

        self.register_tool(
            "get_live_news",
            "Liefert aktuelle Nachrichten und Schlagzeilen zu einem Thema.",
            schema({
                "topic": {"type": "string", "default": "general"},
                "max_results": {"type": "integer", "default": 5},
            }),
            execute_get_news,
            source="builtin_news",
        )

        self.register_tool(
            "get_current_weather",
            "Liefert aktuelle Wetterdaten für einen Ort weltweit.",
            schema({"location": {"type": "string", "description": "Stadt oder Ort."}}, ["location"]),
            execute_get_weather,
            source="builtin_weather",
        )

        self.register_tool(
            "get_weather_forecast",
            "Liefert eine echte 1- bis 16-Tage-Wettervorhersage mit Temperatur, Niederschlag, Wind, Sonnenauf- und -untergang.",
            schema({
                "location": {"type": "string", "description": "Stadt oder Ort."},
                "days": {"type": "integer", "minimum": 1, "maximum": 16, "default": 7},
            }, ["location"], strict=True),
            get_weather_forecast,
            source="builtin_weather",
        )

        self.register_tool(
            "search_events",
            "Durchsucht den ComputeMesh Event-Index nach lokalen Veranstaltungen und liefert kategorisierte Treffer im Radius.",
            schema({
                "city": {"type": "string", "description": "Stadt oder Gemeinde."},
                "radius_km": {"type": "number", "minimum": 1, "maximum": 300, "default": 50},
                "categories": {"type": "array", "items": {"type": "string"}},
                "date_from": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "date_to": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "query_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "day_scope": {"type": "string", "enum": ["today", "today_tomorrow", "range"], "default": "today_tomorrow"},
                "sort": {"type": "string", "enum": ["recommended", "date", "quality"], "default": "recommended"},
                "max_events": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            }, ["city"], strict=True),
            search_events,
            source="builtin_events",
        )

        self.register_tool(
            "search_places",
            "Sucht strukturierte Orte, POIs und benannte lokale Betriebe über OpenStreetMap.",
            schema({
                "query": {"type": "string", "description": "Name oder Art des gesuchten Ortes/Betriebs."},
                "location": {"type": "string", "description": "Optionaler Orts-/Regionskontext."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            }, ["query"], strict=True),
            search_places,
            source="builtin_places",
        )

        self.register_tool(
            "get_sports_data",
            "Liefert aktuelle Team- und Spielplandaten aus der freien TheSportsDB-API.",
            schema({
                "query": {"type": "string", "description": "Teamname für mode=teams."},
                "mode": {"type": "string", "enum": ["teams", "events", "next_league", "previous_league"], "default": "teams"},
                "date": {"type": "string", "description": "YYYY-MM-DD für mode=events."},
                "sport": {"type": "string", "description": "Optionaler Sportfilter."},
                "league": {"type": "string", "description": "Optionaler Ligafilter."},
                "league_id": {"type": "string", "description": "Numerische TheSportsDB League-ID."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            }, strict=True),
            get_sports_data,
            source="builtin_sports",
        )

        self.register_tool(
            "lookup_company",
            "Sucht Rechtsträger im globalen GLEIF-LEI-Register und liefert standardisierte Registrierungs- und Adressdaten.",
            schema({
                "name": {"type": "string", "description": "Unternehmens-/Rechtsträgername."},
                "country": {"type": "string", "description": "Optionaler ISO-2-Ländercode, z. B. DE."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            }, ["name"], strict=True),
            lookup_company,
            source="builtin_company",
        )

        self.register_tool(
            "calculate_math",
            "Führt mathematische Berechnungen in der eingeschränkten Python-Rechenumgebung aus.",
            schema({"expression": {"type": "string"}}, ["expression"]),
            run_python_calc,
            source="builtin_math",
        )

        self.register_tool(
            "get_wikipedia_summary",
            "Liefert lexikalische Zusammenfassungen und Fakten aus Wikipedia.",
            schema({
                "query": {"type": "string"},
                "language": {"type": "string", "default": "de"},
            }, ["query"]),
            get_wikipedia_summary,
            source="builtin_wiki",
        )

        self.register_tool(
            "get_time_and_calendar",
            "Liefert aktuelle Uhrzeit, Zeitzonen-, Kalender- und deutsche Feiertagsdaten.",
            schema({
                "timezone_name": {"type": "string", "default": "Europe/Berlin"},
                "target_date": {"type": "string"},
                "state": {"type": "string", "default": "BY"},
            }),
            get_time_and_calendar,
            source="builtin_time",
        )

        self.register_tool(
            "convert_currency",
            "Rechnet Geldbeträge live zwischen Fiat- und unterstützten Kryptowährungen um.",
            schema({
                "amount": {"type": "number", "default": 1.0},
                "from_currency": {"type": "string", "default": "EUR"},
                "to_currency": {"type": "string", "default": "USD"},
            }, ["amount", "from_currency", "to_currency"]),
            convert_currency,
            source="builtin_currency",
        )

        self.register_tool(
            "get_distance_route",
            "Berechnet Luftlinie, Fahrtstrecke, Koordinaten und Fahrzeit zwischen zwei Orten.",
            schema({
                "origin": {"type": "string"},
                "destination": {"type": "string"},
            }, ["origin", "destination"]),
            get_distance_route,
            source="builtin_geo",
        )

        self.register_tool(
            "lookup_country_data",
            "Liefert strukturierte Länder- und Demografiedaten.",
            schema({"country": {"type": "string"}}, ["country"]),
            lookup_country_data,
            source="builtin_open_data",
        )

        self.register_tool(
            "get_world_bank_stats",
            "Liefert offizielle makroökonomische Indikatoren der Weltbank.",
            schema({
                "country": {"type": "string", "default": "DEU"},
                "indicator": {"type": "string", "default": "gdp"},
            }, ["country"]),
            get_world_bank_stats,
            source="builtin_open_data",
        )

        self.register_tool(
            "search_arxiv_papers",
            "Durchsucht arXiv nach wissenschaftlichen Arbeiten und Preprints.",
            schema({
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            }, ["query"]),
            search_arxiv_papers,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_food_product",
            "Liefert Inhaltsstoffe, Allergene und Nährwerte aus Open Food Facts.",
            schema({"product_name": {"type": "string"}}, ["product_name"]),
            lookup_food_product,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_software_package",
            "Liefert Paketinformationen und bekannte OSV/CVE-Sicherheitslücken für PyPI/NPM.",
            schema({
                "package_name": {"type": "string"},
                "ecosystem": {"type": "string", "default": "pypi"},
            }, ["package_name"]),
            lookup_software_package,
            source="builtin_open_data",
        )

        self.register_tool(
            "get_recent_earthquakes",
            "Liefert aktuelle weltweite Erdbebendaten der USGS.",
            schema({
                "min_magnitude": {"type": "number", "default": 4.0},
                "limit": {"type": "integer", "default": 5},
            }),
            get_recent_earthquakes,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_chemical_compound",
            "Liefert chemische Eigenschaften aus PubChem.",
            schema({"compound_name": {"type": "string"}}, ["compound_name"]),
            lookup_chemical_compound,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_word_definition",
            "Liefert englische Definitionen, Phonetik, Wortarten und Synonyme.",
            schema({"word": {"type": "string"}}, ["word"]),
            lookup_word_definition,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_train_schedule",
            "Liefert Bahn-Abfahrten, Linien, Gleise und Echtzeit-Verspätungen.",
            schema({
                "station": {"type": "string"},
                "max_results": {"type": "integer", "default": 5},
            }, ["station"]),
            lookup_train_schedule,
            source="builtin_open_data",
        )

        self.register_tool(
            "lookup_network_host",
            "Führt sichere Netzwerkdiagnosen für eine öffentliche Domain aus.",
            schema({
                "host": {"type": "string"},
                "check_type": {"type": "string", "default": "all"},
            }, ["host"]),
            lookup_network_host,
            owner_only=True,
            source="builtin_network",
        )

        if self.config.system_tools_enabled:
            self.register_tool(
                "get_system_info",
                "Liefert Host- und Systeminformationen des Compute-Knotens.",
                schema({}),
                execute_system_info,
                owner_only=True,
                source="builtin_system",
            )
