# SPDX-License-Identifier: Apache-2.0
"""
Comprehensive Unit Tests for ComputeMesh MCP Subsystem.
Validates all 21 tools, free database lookups, sandboxing security, tool registry, and agent loop execution.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from services.mcp.config import MCPConfig, get_mcp_config, set_mcp_config
from services.mcp.tool_registry import ToolRegistry, ToolDefinition
from services.mcp.agent_loop import AgentLoop, AgentExecutionResult
from services.mcp.builtin.finance_market import execute_finance_quote, fetch_yahoo_quote
from services.mcp.builtin.web_search import execute_web_search, clean_html
from services.mcp.builtin.web_fetch import execute_web_fetch, clean_web_page_html
from services.mcp.builtin.news_feed import execute_get_news
from services.mcp.builtin.weather import get_current_weather
from services.mcp.builtin.python_calc import run_python_calc
from services.mcp.builtin.wikipedia import get_wikipedia_summary
from services.mcp.builtin.time_calendar import get_time_and_calendar, calculate_easter_sunday, get_german_holidays
from services.mcp.builtin.currency import convert_currency
from services.mcp.builtin.geo_routing import get_distance_route, _haversine_distance_km, _compass_direction
from services.mcp.builtin.country_data import lookup_country_data
from services.mcp.builtin.world_bank import get_world_bank_stats
from services.mcp.builtin.arxiv_research import search_arxiv_papers
from services.mcp.builtin.food_products import lookup_food_product
from services.mcp.builtin.package_registry import lookup_software_package
from services.mcp.builtin.earthquake_feed import get_recent_earthquakes
from services.mcp.builtin.chemical_data import lookup_chemical_compound
from services.mcp.builtin.dictionary_lookup import lookup_word_definition
from services.mcp.builtin.train_transit import lookup_train_schedule
from services.mcp.builtin.network_tools import lookup_network_host, _is_ip_blocked
from services.mcp.builtin.system_tools import execute_system_info


class TestMCPConfig(unittest.TestCase):
    def test_default_config(self):
        cfg = MCPConfig()
        self.assertTrue(cfg.enabled)
        self.assertTrue(cfg.web_search_enabled)
        self.assertTrue(cfg.finance_enabled)
        self.assertTrue(cfg.web_fetch_enabled)
        self.assertFalse(cfg.system_tools_enabled)
        self.assertEqual(cfg.max_agent_iterations, 5)

    def test_from_env(self):
        with patch.dict("os.environ", {
            "COMPUTEMESH_MCP_ENABLED": "false",
            "COMPUTEMESH_MCP_MAX_ITERATIONS": "8",
        }):
            cfg = MCPConfig.from_env()
            self.assertFalse(cfg.enabled)
            self.assertEqual(cfg.max_agent_iterations, 8)


class TestBuiltinTools(unittest.TestCase):
    def test_clean_html(self):
        raw = "<p>Hello <b>World</b> &amp; ComputeMesh!</p>"
        self.assertEqual(clean_html(raw), "Hello World & ComputeMesh!")

    def test_clean_web_page_html(self):
        raw = "<html><head><style>body{color:red;}</style></head><body><h1>Title</h1><p>Paragraph text.</p></body></html>"
        cleaned = clean_web_page_html(raw)
        self.assertIn("Title", cleaned)
        self.assertIn("Paragraph text.", cleaned)
        self.assertNotIn("color:red", cleaned)

    @patch("services.mcp.builtin.web_search.duckduckgo_search")
    def test_web_search_execution(self, mock_ddg):
        mock_ddg.return_value = [
            {"title": "Test Title", "url": "https://example.com", "snippet": "Test snippet"}
        ]
        res = execute_web_search("Python AI")
        self.assertEqual(res["query"], "Python AI")
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["title"], "Test Title")

    def test_web_search_empty(self):
        res = execute_web_search("")
        self.assertIn("error", res)

    @patch("services.mcp.builtin.finance_market.fetch_yahoo_quote")
    def test_finance_quote_stock(self, mock_yahoo):
        mock_yahoo.return_value = {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "price": 230.50,
            "currency": "USD",
            "change": 2.50,
            "change_percent": 1.10,
        }
        res = execute_finance_quote("AAPL")
        self.assertEqual(res["symbol"], "AAPL")
        self.assertEqual(res["price"], 230.50)

    @patch("services.mcp.builtin.finance_market.fetch_coingecko_quote")
    def test_finance_quote_crypto(self, mock_cg):
        mock_cg.return_value = {
            "symbol": "BITCOIN",
            "name": "Bitcoin",
            "price_usd": 65000.0,
            "change_24h_percent": 3.4,
            "source": "coingecko",
        }
        res = execute_finance_quote("BTC")
        self.assertEqual(res["symbol"], "BITCOIN")
        self.assertEqual(res["price_usd"], 65000.0)

    def test_finance_quote_empty(self):
        res = execute_finance_quote("")
        self.assertIn("error", res)

    @patch("services.mcp.builtin.news_feed.fetch_rss_news")
    def test_news_feed(self, mock_rss):
        mock_rss.return_value = [
            {"title": "Breaking News: AI Mesh Breakthrough", "link": "https://news.example.com/1", "source": "TechNews", "published": "2026-09-07", "summary": "Details"}
        ]
        res = execute_get_news("tech")
        self.assertEqual(res["topic"], "tech")
        self.assertEqual(len(res["articles"]), 1)
        self.assertEqual(res["articles"][0]["title"], "Breaking News: AI Mesh Breakthrough")

    def test_weather_tool_empty(self):
        res = get_current_weather("")
        self.assertIn("error", res)

    def test_system_info(self):
        info = execute_system_info()
        self.assertIn("os", info)
        self.assertIn("python_version", info)
        self.assertIn("server_time_utc", info)


class TestSafePythonCalc(unittest.TestCase):
    def test_basic_arithmetic(self):
        res = run_python_calc("2 + 2 * 10")
        self.assertEqual(res.get("result"), 22)
        self.assertEqual(res.get("status"), "success")

    def test_math_module(self):
        res = run_python_calc("math.sqrt(144) + math.pi")
        self.assertAlmostEqual(res.get("result"), 12.0 + 3.14159265, places=4)

    def test_statistics_and_multiline(self):
        code = "data = [10, 20, 30, 40, 50]\nresult = statistics.mean(data)"
        res = run_python_calc(code)
        self.assertEqual(res.get("result"), 30)

    def test_security_import_blocked(self):
        res = run_python_calc("import os; os.system('echo hacked')")
        self.assertIn("error", res)
        self.assertIn("Sicherheitsrichtlinie", res["error"])

    def test_security_open_blocked(self):
        res = run_python_calc("open('/etc/passwd').read()")
        self.assertIn("error", res)

    def test_security_dunder_blocked(self):
        res = run_python_calc("().foo.__class__.__bases__[0].__subclasses__()")
        self.assertIn("error", res)

    def test_security_eval_blocked(self):
        res = run_python_calc("eval('1+1')")
        self.assertIn("error", res)


class TestWikipediaAndCalendar(unittest.TestCase):
    @patch("services.mcp.builtin.wikipedia._fetch_wiki_summary_by_title")
    def test_wikipedia_summary(self, mock_fetch):
        mock_fetch.return_value = {
            "title": "Veitshöchheim",
            "extract": "Veitshöchheim ist eine Gemeinde im unterfränkischen Landkreis Würzburg.",
            "language": "de",
        }
        res = get_wikipedia_summary("Veitshöchheim")
        self.assertEqual(res["title"], "Veitshöchheim")
        self.assertIn("Würzburg", res["extract"])

    def test_easter_and_holidays(self):
        easter_2026 = calculate_easter_sunday(2026)
        self.assertEqual(str(easter_2026), "2026-04-05")

        holidays_by = get_german_holidays(2026, state="BY")
        names = [h["name"] for h in holidays_by]
        self.assertIn("Ostermontag", names)
        self.assertIn("Karfreitag", names)
        self.assertIn("Fronleichnam", names)
        self.assertIn("Tag der Deutschen Einheit", names)

    def test_time_and_calendar_query(self):
        res = get_time_and_calendar(timezone_name="Europe/Berlin", target_date="2026-12-25")
        self.assertIn("datetime_iso", res)
        self.assertIn("calendar_week", res)
        self.assertIn("days_until_target", res)
        self.assertTrue(res["holidays_count"] >= 9)


class TestCurrencyAndGeoRouting(unittest.TestCase):
    def test_identical_currency(self):
        res = convert_currency(100.0, "EUR", "EUR")
        self.assertEqual(res["converted_amount"], 100.0)
        self.assertEqual(res["rate"], 1.0)

    def test_fallback_fiat_rate(self):
        res = convert_currency(100.0, "EUR", "USD")
        self.assertTrue(res.get("converted_amount", 0) > 0)
        self.assertIn("EUR", res.get("from_currency", ""))

    def test_crypto_conversion_mock(self):
        with patch("services.mcp.builtin.currency._fetch_coingecko_crypto") as mock_cg:
            mock_cg.return_value = {
                "coin": "bitcoin",
                "symbol": "BTC",
                "price": 60000.0,
                "vs_currency": "USD",
                "change_24h_percent": 2.5,
            }
            res = convert_currency(0.5, "BTC", "USD")
            self.assertEqual(res["converted_amount"], 30000.0)
            self.assertEqual(res["unit_price"], 60000.0)

    def test_haversine_distance(self):
        dist = _haversine_distance_km(52.5200, 13.4050, 48.1371, 11.5761)
        self.assertTrue(500 < dist < 510)

    def test_compass_direction(self):
        direction = _compass_direction(52.5200, 13.4050, 48.1371, 11.5761)
        self.assertIn(direction, ("SSW", "S", "SW"))

    @patch("services.mcp.builtin.geo_routing._geocode_location")
    @patch("services.mcp.builtin.geo_routing._get_osrm_route")
    def test_get_distance_route_mocked(self, mock_osrm, mock_geo):
        mock_geo.side_effect = [
            {"display_name": "Veitshöchheim, Bayern", "lat": 49.833, "lon": 9.873, "type": "village"},
            {"display_name": "Würzburg, Bayern", "lat": 49.794, "lon": 9.929, "type": "city"},
        ]
        mock_osrm.return_value = {
            "driving_distance_km": 7.5,
            "driving_duration_seconds": 600,
            "driving_duration_formatted": "10 Min.",
        }
        res = get_distance_route(origin="Veitshöchheim", destination="Würzburg")
        self.assertEqual(res["driving_distance_km"], 7.5)
        self.assertEqual(res["driving_duration_formatted"], "10 Min.")
        self.assertIn("summary", res)


class TestFreeDatabaseIntelligence(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_country_data_mocked(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{
            "name": {"common": "Japan", "official": "State of Japan"},
            "capital": ["Tokyo"],
            "population": 125000000,
            "region": "Asia",
            "currencies": {"JPY": {"name": "Japanese yen", "symbol": "¥"}},
            "languages": {"jpn": "Japanese"},
            "borders": [],
            "timezones": ["UTC+09:00"],
            "area": 377975,
        }]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = lookup_country_data("Japan")
        self.assertEqual(res["country_name"], "Japan")
        self.assertEqual(res["capital"], "Tokyo")
        self.assertEqual(res["population"], 125000000)

    @patch("urllib.request.urlopen")
    def test_world_bank_mocked(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {"page": 1, "pages": 1, "per_page": 50, "total": 2},
            [
                {"indicator": {"id": "NY.GDP.MKTP.CD"}, "country": {"id": "DE", "value": "Germany"}, "date": "2023", "value": 4456000000000.0},
                {"indicator": {"id": "NY.GDP.MKTP.CD"}, "country": {"id": "DE", "value": "Germany"}, "date": "2022", "value": 4082000000000.0},
            ]
        ]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = get_world_bank_stats(country="DEU", indicator="gdp")
        self.assertEqual(res["country"], "Germany")
        self.assertEqual(res["latest_year"], "2023")
        self.assertEqual(res["latest_value"], 4456000000000.0)

    @patch("urllib.request.urlopen")
    def test_arxiv_research_mocked(self, mock_urlopen):
        sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>http://arxiv.org/abs/2401.00001v1</id>
            <title>Advances in Deep Reasoning Models</title>
            <summary>This paper introduces new methods for multi-step reasoning.</summary>
            <published>2026-01-01T12:00:00Z</published>
            <author><name>Dr. Alice Smith</name></author>
          </entry>
        </feed>"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_xml
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = search_arxiv_papers("deep reasoning")
        self.assertEqual(res["papers_found"], 1)
        self.assertEqual(res["papers"][0]["title"], "Advances in Deep Reasoning Models")
        self.assertIn("Dr. Alice Smith", res["papers"][0]["authors"])

    @patch("services.mcp.builtin.food_products._search_by_name")
    def test_food_product_mocked(self, mock_search):
        mock_search.return_value = {
            "product_name": "Nutella",
            "brands": "Ferrero",
            "code": "3017620422003",
            "nutriscore_grade": "e",
            "ecoscore_grade": "d",
            "ingredients_text": "Zucker, Palmöl, Haselnüsse (13%), Magermilchpulver (8,7%), fettarmer Kakao (7,4%)",
            "nutriments": {"energy-kcal_100g": 539, "fat_100g": 30.9, "sugars_100g": 56.3, "proteins_100g": 6.3},
        }
        res = lookup_food_product("Nutella")
        self.assertEqual(res["product_name"], "Nutella")
        self.assertEqual(res["brand"], "Ferrero")
        self.assertEqual(res["nutriscore"], "E")
        self.assertEqual(res["nutrition_per_100g"]["brennwert_kcal_100g"], 539)

    @patch("services.mcp.builtin.package_registry._fetch_pypi")
    @patch("services.mcp.builtin.package_registry._check_osv_vulnerabilities")
    def test_software_package_mocked(self, mock_osv, mock_pypi):
        mock_pypi.return_value = {
            "ecosystem": "PyPI (Python)",
            "name": "fastapi",
            "version": "0.115.0",
            "summary": "FastAPI framework, high performance",
            "license": "MIT",
            "dependencies_count": 5,
        }
        mock_osv.return_value = []
        res = lookup_software_package("fastapi", ecosystem="pypi")
        self.assertEqual(res["name"], "fastapi")
        self.assertEqual(res["vulnerabilities_count"], 0)
        self.assertIn("v0.115.0", res["summary_formatted"])

    @patch("urllib.request.urlopen")
    def test_earthquakes_mocked(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "features": [{
                "properties": {
                    "mag": 6.2,
                    "place": "120 km E of Tokyo, Japan",
                    "time": 1788800000000,
                    "tsunami": 0,
                    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us1000",
                },
                "geometry": {"coordinates": [141.5, 36.2, 25.0]},
            }]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = get_recent_earthquakes(min_magnitude=5.0)
        self.assertEqual(res["earthquakes_count"], 1)
        self.assertEqual(res["events"][0]["magnitude"], 6.2)
        self.assertIn("Tokyo", res["events"][0]["place"])

    @patch("urllib.request.urlopen")
    def test_chemical_compound_mocked(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "PropertyTable": {
                "Properties": [{
                    "CID": 2244,
                    "MolecularFormula": "C9H8O4",
                    "MolecularWeight": "180.16",
                    "IUPACName": "2-acetyloxybenzoic acid",
                    "CanonicalSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                    "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
                }]
            }
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = lookup_chemical_compound("Aspirin")
        self.assertEqual(res["molecular_formula"], "C9H8O4")
        self.assertEqual(res["pubchem_cid"], 2244)
        self.assertEqual(res["molecular_weight_g_mol"], "180.16")

    @patch("urllib.request.urlopen")
    def test_word_definition_mocked(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{
            "word": "serendipity",
            "phonetic": "/ˌsɛr.ənˈdɪp.ɪ.ti/",
            "meanings": [{
                "partOfSpeech": "noun",
                "definitions": [{"definition": "The occurrence and development of events by chance in a happy way."}],
                "synonyms": ["chance", "fluke"],
            }]
        }]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = lookup_word_definition("serendipity")
        self.assertEqual(res["word"], "serendipity")
        self.assertIn("/ˌsɛr.ənˈdɪp.ɪ.ti/", res["phonetic"])
        self.assertEqual(res["meanings"][0]["part_of_speech"], "noun")

    @patch("services.mcp.builtin.train_transit._find_station_id")
    @patch("urllib.request.urlopen")
    def test_train_transit_mocked(self, mock_urlopen, mock_station):
        mock_station.return_value = {"id": "8000261", "name": "Würzburg Hbf"}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "departures": [{
                "line": {"name": "ICE 628"},
                "direction": "Frankfurt(Main)Hbf",
                "plannedWhen": "2026-09-07T14:30:00+02:00",
                "when": "2026-09-07T14:32:00+02:00",
                "delay": 120,
                "platform": "5",
                "cancelled": False,
            }]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = lookup_train_schedule("Würzburg Hbf")
        self.assertEqual(res["station_name"], "Würzburg Hbf")
        self.assertEqual(res["departures_count"], 1)
        self.assertEqual(res["departures"][0]["line"], "ICE 628")
        self.assertEqual(res["departures"][0]["delay_minutes"], 2)


class TestNetworkDiagnosticsAndSSRF(unittest.TestCase):
    def test_ssrf_ip_blocking(self):
        self.assertTrue(_is_ip_blocked("127.0.0.1"))
        self.assertTrue(_is_ip_blocked("10.0.0.1"))
        self.assertTrue(_is_ip_blocked("192.168.1.1"))
        self.assertTrue(_is_ip_blocked("172.16.0.1"))
        self.assertTrue(_is_ip_blocked("169.254.169.254"))
        self.assertTrue(_is_ip_blocked("::1"))
        self.assertFalse(_is_ip_blocked("8.8.8.8"))
        self.assertFalse(_is_ip_blocked("1.1.1.1"))

    def test_lookup_blocked_hosts(self):
        res = lookup_network_host("localhost")
        self.assertIn("error", res)
        self.assertIn("Sicherheitsrichtlinie", res["error"])

        res_internal = lookup_network_host("cluster.local")
        self.assertIn("error", res_internal)
        self.assertIn("Sicherheitsrichtlinie", res_internal["error"])


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry(MCPConfig(system_tools_enabled=True))

    def test_registered_tools(self):
        tools = self.registry.list_tools(is_owner=True)
        names = [t.name for t in tools]
        expected = [
            "search_web",
            "get_market_quote",
            "fetch_web_content",
            "get_live_news",
            "get_current_weather",
            "calculate_math",
            "get_wikipedia_summary",
            "get_time_and_calendar",
            "convert_currency",
            "get_distance_route",
            "lookup_country_data",
            "get_world_bank_stats",
            "search_arxiv_papers",
            "lookup_food_product",
            "lookup_software_package",
            "get_recent_earthquakes",
            "lookup_chemical_compound",
            "lookup_word_definition",
            "lookup_train_schedule",
            "lookup_network_host",
            "get_system_info",
        ]
        for exp in expected:
            self.assertIn(exp, names)

    def test_owner_only_filtering(self):
        non_owner_tools = self.registry.list_tools(is_owner=False)
        names = [t.name for t in non_owner_tools]
        self.assertNotIn("lookup_network_host", names)
        self.assertNotIn("get_system_info", names)
        self.assertIn("calculate_math", names)
        self.assertIn("convert_currency", names)
        self.assertIn("lookup_country_data", names)
        self.assertIn("get_world_bank_stats", names)

    def test_openai_format(self):
        openai_tools = self.registry.get_openai_tools(is_owner=True)
        self.assertTrue(len(openai_tools) >= 15)
        first = openai_tools[0]
        self.assertEqual(first.get("type"), "function")
        self.assertIn("name", first.get("function", {}))
        self.assertIn("description", first.get("function", {}))
        self.assertIn("parameters", first.get("function", {}))

    def test_execute_tool_success(self):
        res = self.registry.execute_tool("calculate_math", {"expression": "100 * 5"})
        self.assertEqual(res.get("result"), 500)

    def test_execute_owner_only_blocked(self):
        res = self.registry.execute_tool("lookup_network_host", {"host": "example.com"}, is_owner=False)
        self.assertIn("error", res)
        self.assertIn("Owner Key", res["error"])


class TestAgentLoop(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register_tool(
            name="get_stock_price",
            description="Gets stock price",
            parameters={"type": "object", "properties": {"symbol": {"type": "string"}}},
            handler=lambda symbol: {"symbol": symbol, "price": 180.0},
        )
        self.loop = AgentLoop(registry=self.registry)

    def test_agent_loop_direct_answer(self):
        def fake_llm(messages, tools):
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": "Hallo! Wie kann ich helfen?"}
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

        res = self.loop.run(
            messages=[{"role": "user", "content": "Hallo"}],
            model="qwen2.5:7b",
            llm_caller=fake_llm,
        )
        self.assertEqual(res.final_content, "Hallo! Wie kann ich helfen?")
        self.assertEqual(len(res.tool_calls_executed), 0)
        self.assertEqual(res.iterations, 1)

    def test_agent_loop_with_tool_call(self):
        calls_count = 0

        def fake_llm(messages, tools):
            nonlocal calls_count
            calls_count += 1
            if calls_count == 1:
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "tool_calls": [{
                                "id": "call_abc_1",
                                "type": "function",
                                "function": {
                                    "name": "get_stock_price",
                                    "arguments": json.dumps({"symbol": "NVDA"}),
                                },
                            }]
                        }
                    }],
                    "usage": {"prompt_tokens": 15, "completion_tokens": 8},
                }
            else:
                return {
                    "choices": [{
                        "message": {"role": "assistant", "content": "Nvidia steht aktuell bei $180.0."}
                    }],
                    "usage": {"prompt_tokens": 30, "completion_tokens": 10},
                }

        res = self.loop.run(
            messages=[{"role": "user", "content": "Wie steht Nvidia?"}],
            model="qwen2.5:7b",
            llm_caller=fake_llm,
        )
        self.assertEqual(res.final_content, "Nvidia steht aktuell bei $180.0.")
        self.assertEqual(len(res.tool_calls_executed), 1)
        self.assertEqual(res.tool_calls_executed[0].name, "get_stock_price")
        self.assertEqual(res.tool_calls_executed[0].result, {"symbol": "NVDA", "price": 180.0})
        self.assertEqual(res.iterations, 2)

    def test_agent_loop_with_markdown_json_block(self):
        calls_count = 0

        def fake_llm(messages, tools):
            nonlocal calls_count
            calls_count += 1
            if calls_count == 1:
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Hier ist die Abfrage:\n```json\n{\n  \"name\": \"get_stock_price\",\n  \"arguments\": {\"symbol\": \"AAPL\"}\n}\n```",
                        }
                    }],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 15},
                }
            else:
                return {
                    "choices": [{
                        "message": {"role": "assistant", "content": "Apple steht bei $180.0."}
                    }],
                    "usage": {"prompt_tokens": 40, "completion_tokens": 8},
                }

        res = self.loop.run(
            messages=[{"role": "user", "content": "Wie steht Apple?"}],
            model="qwen2.5:7b",
            llm_caller=fake_llm,
        )
        self.assertEqual(res.final_content, "Apple steht bei $180.0.")
        self.assertEqual(len(res.tool_calls_executed), 1)
        self.assertEqual(res.tool_calls_executed[0].name, "get_stock_price")


if __name__ == "__main__":
    unittest.main()
