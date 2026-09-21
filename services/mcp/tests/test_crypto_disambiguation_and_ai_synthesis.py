# SPDX-License-Identifier: Apache-2.0
"""
Tests for Financial Context Disambiguation, Multi-Crypto Quotes,
and AI Synthesis in ComputeMesh MCP subsystem.
"""

import unittest
from services.mcp.intent.intent_router import (
    detect_direct_tool_intent,
    detect_compound_tool_intents,
    is_compound_multi_step_query,
)
from services.mcp.tool_registry import ToolRegistry
from services.mcp.formatting.tool_formatter import format_tool_content_if_json


class TestCryptoDisambiguationAndSynthesis(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_bitcoin_ethereum_24h_trend_intent(self):
        """User prompt asking for BTC and ETH prices and 24h trend must route directly to get_market_quote."""
        query = "Wie steht der Bitcoin (BTC) und Ethereum (ETH) Kurs aktuell und was ist der 24h Trend?"
        
        # 1. Must NOT be treated as multi-domain compound query
        self.assertFalse(is_compound_multi_step_query(query))
        
        # 2. Must detect direct market quote intent containing both BTC and ETH
        direct = detect_direct_tool_intent(query, self.registry)
        self.assertIsNotNone(direct)
        tool_name, tool_args = direct
        self.assertEqual(tool_name, "get_market_quote")
        self.assertIn("BTC", tool_args.get("symbol", ""))
        self.assertIn("ETH", tool_args.get("symbol", ""))

        # 3. Compound scan must NOT contain Wikipedia or News
        compounds = detect_compound_tool_intents(query, self.registry)
        tool_names = [c[0] for c in compounds]
        self.assertNotIn("get_wikipedia_summary", tool_names)
        self.assertNotIn("get_live_news", tool_names)

    def test_aktuell_keyword_does_not_trigger_news_in_other_domains(self):
        """The word 'aktuell' by itself in weather/stock/time queries must not trigger news feed."""
        weather_q = "Wie ist das Wetter in Berlin aktuell?"
        w_direct = detect_direct_tool_intent(weather_q, self.registry)
        self.assertIsNotNone(w_direct)
        self.assertEqual(w_direct[0], "get_current_weather")
        
        w_compounds = detect_compound_tool_intents(weather_q, self.registry)
        self.assertNotIn("get_live_news", [c[0] for c in w_compounds])

        btc_q = "Wie steht Bitcoin aktuell?"
        b_direct = detect_direct_tool_intent(btc_q, self.registry)
        self.assertIsNotNone(b_direct)
        self.assertEqual(b_direct[0], "get_market_quote")
        
        b_compounds = detect_compound_tool_intents(btc_q, self.registry)
        self.assertNotIn("get_live_news", [c[0] for c in b_compounds])

    def test_24h_metric_does_not_trigger_wikipedia(self):
        """Phrases asking for 24h trend/metrics must not trigger Wikipedia lookup."""
        q_trend = "Was ist der 24h Trend?"
        w_intent = detect_direct_tool_intent(q_trend, self.registry)
        if w_intent:
            self.assertNotEqual(w_intent[0], "get_wikipedia_summary")

        q_price = "Was ist der Kurs von Apple?"
        p_intent = detect_direct_tool_intent(q_price, self.registry)
        self.assertIsNotNone(p_intent)
        self.assertEqual(p_intent[0], "get_market_quote")

    def test_genuine_wikipedia_still_works(self):
        """Genuine encyclopedia questions should still route to Wikipedia."""
        q_einstein = "Wer war Albert Einstein?"
        e_intent = detect_direct_tool_intent(q_einstein, self.registry)
        self.assertIsNotNone(e_intent)
        self.assertEqual(e_intent[0], "get_wikipedia_summary")
        self.assertIn("Albert Einstein", e_intent[1].get("query", ""))

        q_physics = "Was ist Quantenphysik?"
        qp_intent = detect_direct_tool_intent(q_physics, self.registry)
        self.assertIsNotNone(qp_intent)
        self.assertEqual(qp_intent[0], "get_wikipedia_summary")
        self.assertIn("Quantenphysik", qp_intent[1].get("query", ""))

    def test_multi_quote_tool_execution_and_formatting(self):
        """Multi-symbol quote tool execution returns structured data with 24h metrics and dual currency."""
        fake_multi_res = {
            "multiple_symbols": True,
            "quotes": [
                {
                    "symbol": "BTC",
                    "name": "Bitcoin",
                    "price_usd": 86036,
                    "price_eur": 79100,
                    "change_24h_percent": 5.99,
                    "source": "coingecko"
                },
                {
                    "symbol": "ETH",
                    "name": "Ethereum",
                    "price_usd": 3120,
                    "price_eur": 2860,
                    "change_24h_percent": 3.45,
                    "source": "coingecko"
                }
            ],
            "count": 2
        }
        import json
        formatted = format_tool_content_if_json(json.dumps(fake_multi_res))
        self.assertIn("Finanz- & Börsenkurs-Übersicht", formatted)
        self.assertIn("86036 USD (~79100 EUR)", formatted)
        self.assertIn("+5.99%", formatted)
        self.assertIn("3120 USD (~2860 EUR)", formatted)
        self.assertIn("+3.45%", formatted)
        self.assertIn("24h Trend / Veränderung", formatted)


if __name__ == "__main__":
    unittest.main()
