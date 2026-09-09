# SPDX-License-Identifier: Apache-2.0
"""Focused regression tests for the completed MCP live-data surface."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from services.mcp.config import MCPConfig
from services.mcp.tool_registry import ToolRegistry
from services.mcp.builtin.company_lookup import lookup_company
from services.mcp.builtin.events import search_events
from services.mcp.builtin.http_json import ProviderError, fetch_json
from services.mcp.builtin.places import search_places
from services.mcp.builtin.sports_data import get_sports_data
from services.mcp.builtin.weather_forecast import get_weather_forecast


class _Response:
    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return self.body


class TestProviderHTTP(unittest.TestCase):
    def test_rejects_non_allowlisted_host_before_network(self):
        with patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(ProviderError):
                fetch_json("https://127.0.0.1/private", allowed_hosts={"api.example.com"})
            urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_successful_json(self, urlopen):
        urlopen.return_value = _Response(b'{"ok": true}')
        self.assertEqual(
            fetch_json("https://api.example.com/data", allowed_hosts={"api.example.com"}),
            {"ok": True},
        )

    @patch("urllib.request.urlopen", side_effect=TimeoutError("timed out"))
    def test_timeout_normalized(self, _urlopen):
        with self.assertRaisesRegex(ProviderError, "Provider nicht erreichbar"):
            fetch_json("https://api.example.com/data", allowed_hosts={"api.example.com"})

    @patch("urllib.request.urlopen")
    def test_http_error_normalized(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://api.example.com/data", 503, "Unavailable", {}, None
        )
        with self.assertRaisesRegex(ProviderError, "HTTP 503"):
            fetch_json("https://api.example.com/data", allowed_hosts={"api.example.com"})

    @patch("urllib.request.urlopen")
    def test_malformed_json_rejected(self, urlopen):
        urlopen.return_value = _Response(b"not-json")
        with self.assertRaisesRegex(ProviderError, "kein gültiges"):
            fetch_json("https://api.example.com/data", allowed_hosts={"api.example.com"})

    @patch("urllib.request.urlopen")
    def test_oversized_response_rejected(self, urlopen):
        urlopen.return_value = _Response(b"x" * 17)
        with self.assertRaisesRegex(ProviderError, "Größenlimit"):
            fetch_json("https://api.example.com/data", allowed_hosts={"api.example.com"}, max_bytes=16)


class TestNewLiveTools(unittest.TestCase):
    @patch("services.mcp.builtin.places.fetch_json")
    def test_search_places_normalizes_results(self, fetch):
        fetch.return_value = [{
            "display_name": "Residenz Würzburg, Bayern, Deutschland",
            "lat": "49.7928",
            "lon": "9.9390",
            "category": "tourism",
            "type": "attraction",
            "osm_type": "relation",
            "osm_id": 123,
            "namedetails": {"name": "Würzburger Residenz"},
            "address": {"city": "Würzburg", "country": "Deutschland"},
        }]
        result = search_places("Residenz", "Würzburg")
        self.assertEqual(result["results_count"], 1)
        self.assertEqual(result["results"][0]["name"], "Würzburger Residenz")
        self.assertAlmostEqual(result["results"][0]["latitude"], 49.7928)

    @patch("services.mcp.builtin.places.fetch_json", side_effect=ProviderError("timeout"))
    def test_search_places_provider_error(self, _fetch):
        result = search_places("Museum", "Würzburg")
        self.assertEqual(result["error"], "timeout")
        self.assertEqual(result["provider"], "OpenStreetMap Nominatim")

    @patch("services.mcp.builtin.company_lookup.fetch_json")
    def test_lookup_company_normalizes_gleif(self, fetch):
        fetch.return_value = {
            "data": [{
                "id": "TESTLEI123",
                "attributes": {
                    "lei": "TESTLEI123",
                    "entity": {
                        "legalName": {"name": "Example GmbH"},
                        "status": "ACTIVE",
                        "jurisdiction": "DE",
                        "category": "GENERAL",
                        "legalAddress": {"city": "Würzburg", "country": "DE", "postalCode": "97070"},
                    },
                    "registration": {"status": "ISSUED", "lastUpdateDate": "2026-09-01T00:00:00Z"},
                },
            }],
            "meta": {"pagination": {"total": 1}},
        }
        result = lookup_company("Example GmbH", country="DE")
        self.assertEqual(result["results_count"], 1)
        self.assertEqual(result["companies"][0]["lei"], "TESTLEI123")
        self.assertEqual(result["companies"][0]["legal_address"]["city"], "Würzburg")

    @patch("services.mcp.builtin.company_lookup.fetch_json", return_value={"unexpected": []})
    def test_lookup_company_malformed_provider_payload(self, _fetch):
        result = lookup_company("Example GmbH")
        self.assertIn("unerwartetes Antwortformat", result["error"])

    @patch("services.mcp.builtin.sports_data.fetch_json")
    def test_sports_team_search(self, fetch):
        fetch.return_value = {"teams": [{
            "idTeam": "133602",
            "strTeam": "Liverpool",
            "strSport": "Soccer",
            "strLeague": "English Premier League",
            "idLeague": "4328",
            "strCountry": "England",
            "intFormedYear": "1892",
            "strStadium": "Anfield",
        }]}
        result = get_sports_data(query="Liverpool", mode="teams")
        self.assertEqual(result["results_count"], 1)
        self.assertEqual(result["results"][0]["stadium"], "Anfield")

    @patch("services.mcp.builtin.sports_data.fetch_json")
    def test_sports_events_by_date(self, fetch):
        fetch.return_value = {"events": [{
            "idEvent": "1",
            "strEvent": "Team A vs Team B",
            "strSport": "Soccer",
            "dateEvent": "2026-09-10",
            "strHomeTeam": "Team A",
            "strAwayTeam": "Team B",
        }]}
        result = get_sports_data(mode="events", date="2026-09-10", sport="Soccer")
        self.assertEqual(result["results"][0]["home_team"], "Team A")

    def test_sports_rejects_bad_date(self):
        self.assertIn("error", get_sports_data(mode="events", date="10.09.2026"))

    @patch("services.mcp.builtin.weather_forecast._geocode")
    @patch("services.mcp.builtin.weather_forecast.fetch_json")
    def test_weather_forecast(self, fetch, geocode):
        geocode.return_value = {
            "name": "Würzburg", "admin1": "Bayern", "country": "Deutschland",
            "latitude": 49.79, "longitude": 9.95,
        }
        fetch.return_value = {
            "timezone": "Europe/Berlin",
            "daily": {
                "time": ["2026-09-10", "2026-09-11"],
                "weather_code": [1, 61],
                "temperature_2m_max": [24.0, 20.0],
                "temperature_2m_min": [12.0, 11.0],
                "precipitation_sum": [0.0, 4.2],
                "precipitation_probability_max": [5, 70],
                "wind_speed_10m_max": [14.0, 22.0],
                "sunrise": ["06:45", "06:47"],
                "sunset": ["19:42", "19:40"],
            },
        }
        result = get_weather_forecast("Würzburg", days=2)
        self.assertEqual(result["days"], 2)
        self.assertEqual(result["forecast"][1]["condition"], "Leichter Regen")
        self.assertEqual(result["forecast"][1]["precipitation_probability_max_percent"], 70)

    @patch("services.mcp.builtin.events._get_engine")
    def test_search_events_delegates_to_existing_engine(self, get_engine):
        engine = MagicMock()
        engine.research_events.return_value = {"city": "Würzburg", "rubrics": {"Konzerte": []}}
        get_engine.return_value = engine
        result = search_events("Würzburg", radius_km=100, categories=["concert"])
        self.assertEqual(result["city"], "Würzburg")
        request = engine.research_events.call_args.args[0]
        self.assertEqual(request.radius_km, 100.0)
        self.assertEqual(request.categories, ["concert"])
        self.assertFalse(request.force_refresh)


class TestCompletedRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry(MCPConfig(system_tools_enabled=True))

    def test_all_completed_tools_registered(self):
        names = {tool.name for tool in self.registry.list_tools(is_owner=True)}
        self.assertEqual(len(names), 26)
        for name in {
            "search_events", "search_places", "get_weather_forecast",
            "get_sports_data", "lookup_company",
        }:
            self.assertIn(name, names)

    def test_fixed_aliases_resolve_to_real_tools(self):
        self.assertEqual(self.registry.get_tool("dns").name, "lookup_network_host")
        self.assertEqual(self.registry.get_tool("get_top_news").name, "get_live_news")
        self.assertEqual(self.registry.get_tool("weather_forecast").name, "get_weather_forecast")

    def test_strict_schema_rejects_unknown_operator_parameter(self):
        result = self.registry.execute_tool(
            "search_events",
            {"city": "Würzburg", "force_refresh": True},
            is_owner=False,
        )
        self.assertIn("Unbekannte Tool-Parameter", result["error"])

    def test_strict_schema_rejects_out_of_range(self):
        result = self.registry.execute_tool(
            "get_weather_forecast",
            {"location": "Würzburg", "days": 99},
        )
        self.assertIn("über dem Maximum", result["error"])


if __name__ == "__main__":
    unittest.main()
