# SPDX-License-Identifier: Apache-2.0
"""
Comprehensive Unit Tests for ComputeMesh MCP Subsystem.
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
        from services.mcp.builtin.news_feed import execute_get_news
        res = execute_get_news("tech")
        self.assertEqual(res["topic"], "tech")
        self.assertEqual(len(res["articles"]), 1)
        self.assertEqual(res["articles"][0]["title"], "Breaking News: AI Mesh Breakthrough")

    def test_weather_tool(self):
        from services.mcp.builtin.weather import get_current_weather
        res = get_current_weather("")
        self.assertIn("error", res)

    def test_system_info(self):
        info = execute_system_info()
        self.assertIn("os", info)
        self.assertIn("python_version", info)
        self.assertIn("server_time_utc", info)


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry(MCPConfig(system_tools_enabled=True))

    def test_registered_tools(self):
        tools = self.registry.list_tools(is_owner=True)
        names = [t.name for t in tools]
        self.assertIn("search_web", names)
        self.assertIn("get_market_quote", names)
        self.assertIn("fetch_web_content", names)
        self.assertIn("get_live_news", names)
        self.assertIn("get_current_weather", names)
        self.assertIn("get_system_info", names)

    def test_openai_format(self):
        openai_tools = self.registry.get_openai_tools(is_owner=True)
        self.assertTrue(len(openai_tools) >= 3)
        first = openai_tools[0]
        self.assertEqual(first.get("type"), "function")
        self.assertIn("name", first.get("function", {}))
        self.assertIn("description", first.get("function", {}))
        self.assertIn("parameters", first.get("function", {}))

    def test_execute_tool_success(self):
        self.registry.register_tool(
            name="custom_calc",
            description="Adds two numbers",
            parameters={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
            handler=lambda a, b: a + b,
        )
        res = self.registry.execute_tool("custom_calc", {"a": 10, "b": 25})
        self.assertEqual(res, 35)

    def test_execute_tool_not_found(self):
        res = self.registry.execute_tool("nonexistent_tool", {})
        self.assertIn("error", res)

    def test_execute_owner_only_blocked(self):
        self.registry.register_tool(
            name="secret_tool",
            description="Owner only",
            parameters={},
            handler=lambda: "secret",
            owner_only=True,
        )
        res = self.registry.execute_tool("secret_tool", {}, is_owner=False)
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
