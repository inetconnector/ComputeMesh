# SPDX-License-Identifier: Apache-2.0
"""
Comprehensive Unit Tests for ComputeMesh MCP Subsystem.
Validates all tools, sandboxing security, tool registry, and agent loop execution.
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
from services.mcp.builtin.network_tools import lookup_network_host, _is_ip_blocked
from services.mcp.builtin.system_tools import execute_system_info
from services.mcp.mcp_client import MCPClient, MCPStdioClient


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
        # In 2026, Easter Sunday is on April 5
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
        # Distance between Berlin (52.52, 13.405) and Munich (48.137, 11.576) is approx 504 km
        dist = _haversine_distance_km(52.5200, 13.4050, 48.1371, 11.5761)
        self.assertTrue(500 < dist < 510)

    def test_compass_direction(self):
        # Moving south from Berlin to Munich
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

    def test_openai_format(self):
        openai_tools = self.registry.get_openai_tools(is_owner=True)
        self.assertTrue(len(openai_tools) >= 10)
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
                # Step 1: Model emits a tool call
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
                # Step 2: Model sees tool result and emits final answer
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


if __name__ == "__main__":
    unittest.main()
