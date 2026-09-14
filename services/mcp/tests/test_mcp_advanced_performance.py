# SPDX-License-Identifier: Apache-2.0
"""High-performance and capability tests for the upgraded ComputeMesh MCP Suite."""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch, MagicMock

from services.mcp.agent_loop import AgentLoop, detect_direct_tool_intent, format_tool_content_if_json
from services.mcp.config import MCPConfig
from services.mcp.tool_registry import ToolRegistry, ToolCache


class TestMCPAdvancedPerformance(unittest.TestCase):
    def setUp(self):
        self.config = MCPConfig(system_tools_enabled=True)
        self.registry = ToolRegistry(self.config)
        self.loop = AgentLoop(registry=self.registry, config=self.config)

    def test_tool_cache_hit_and_eviction(self):
        cache = ToolCache(max_size=5)
        # Test cache miss
        hit, val = cache.get("get_market_quote", {"symbol": "BTC"})
        self.assertFalse(hit)
        self.assertIsNone(val)

        # Test cache set and hit
        cache.set("get_market_quote", {"symbol": "BTC"}, {"price": 60000})
        hit, val = cache.get("get_market_quote", {"symbol": "BTC"})
        self.assertTrue(hit)
        self.assertEqual(val["price"], 60000)

        # Test error results are not cached
        cache.set("get_market_quote", {"symbol": "INVALID"}, {"error": "not found"})
        hit, _ = cache.get("get_market_quote", {"symbol": "INVALID"})
        self.assertFalse(hit)

    def test_execute_tools_batch_parallel_speedup(self):
        called = []

        def slow_handler_1(x: int = 1):
            time.sleep(0.05)
            called.append(1)
            return {"r": x * 2}

        def slow_handler_2(y: int = 2):
            time.sleep(0.05)
            called.append(2)
            return {"r": y * 3}

        self.registry.register_tool("slow_1", "slow 1", {"type": "object", "properties": {"x": {"type": "integer"}}}, slow_handler_1)
        self.registry.register_tool("slow_2", "slow 2", {"type": "object", "properties": {"y": {"type": "integer"}}}, slow_handler_2)

        tool_calls = [
            {"id": "call_1", "type": "function", "function": {"name": "slow_1", "arguments": json.dumps({"x": 5})}},
            {"id": "call_2", "type": "function", "function": {"name": "slow_2", "arguments": json.dumps({"y": 10})}},
        ]

        t0 = time.time()
        results = self.registry.execute_tools_batch(tool_calls)
        elapsed = time.time() - t0

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["result"]["r"], 10)
        self.assertEqual(results[1]["result"]["r"], 30)
        self.assertIn(1, called)
        self.assertIn(2, called)
        # In parallel, both run simultaneously so elapsed is < 0.12s rather than >= 0.10s
        self.assertLess(elapsed, 0.25)

    def test_generate_ai_image_tool_structure(self):
        tool = self.registry.get_tool("generate_ai_image")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "generate_ai_image")
        self.assertIn("prompt", tool.parameters["properties"])
        self.assertIn("style", tool.parameters["properties"])

        # Check aliases
        self.assertEqual(self.registry.get_tool("generate_image").name, "generate_ai_image")
        self.assertEqual(self.registry.get_tool("bild_generieren").name, "generate_ai_image")
        self.assertEqual(self.registry.get_tool("create_image").name, "generate_ai_image")

    def test_check_url_safety_tool(self):
        tool = self.registry.get_tool("check_url_safety")
        self.assertIsNotNone(tool)

        # Test local / private IP blocking
        res_blocked = self.registry.execute_tool("check_url_safety", {"url": "http://127.0.0.1:8080/secret"})
        self.assertFalse(res_blocked["safe"])
        self.assertEqual(res_blocked["status"], "BLOCKED")

        # Test public IP validation (e.g. 8.8.8.8)
        res_public = self.registry.execute_tool("check_url_safety", {"url": "http://8.8.8.8"})
        self.assertTrue(res_public["safe"])
        self.assertEqual(res_public["status"], "CLEAN")

    def test_direct_intent_detection_image_and_security(self):
        intent_img = detect_direct_tool_intent("Erstelle ein Foto von einem alten Segelschiff im Sturm")
        self.assertIsNotNone(intent_img)
        self.assertEqual(intent_img[0], "generate_ai_image")
        self.assertEqual(intent_img[1]["style"], "photorealistic")

        intent_anime = detect_direct_tool_intent("Zeichne ein Anime Bild von einem fliegenden Drachen")
        self.assertIsNotNone(intent_anime)
        self.assertEqual(intent_anime[0], "generate_ai_image")
        self.assertEqual(intent_anime[1]["style"], "anime")

        intent_url = detect_direct_tool_intent("Prüfe die URL https://example.com auf Sicherheit")
        self.assertIsNotNone(intent_url)
        self.assertEqual(intent_url[0], "check_url_safety")
        self.assertEqual(intent_url[1]["url"], "https://example.com")

    def test_format_tool_content_image_and_security(self):
        img_payload = json.dumps({
            "status": "success",
            "image_url": "data:image/png;base64,iVBORw0KGgoAAA...",
            "markdown": "![Drache](data:image/png;base64,iVBORw0KGgoAAA...)\n\n[⬇️ **Download**](data:image/png;base64,iVBORw0KGgoAAA...)"
        })
        formatted_img = format_tool_content_if_json(img_payload)
        self.assertIn("![Drache]", formatted_img)
        self.assertIn("Download", formatted_img)

        sec_payload = json.dumps({
            "safe": True,
            "status": "CLEAN",
            "url": "https://example.com",
            "hostname": "example.com",
            "resolved_public_ips": ["93.184.216.34"],
            "message": "URL ist sicher."
        })
        formatted_sec = format_tool_content_if_json(sec_payload)
        self.assertIn("URL-Sicherheitsprüfung", formatted_sec)
        self.assertIn("SICHER", formatted_sec)
