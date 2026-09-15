# SPDX-License-Identifier: Apache-2.0
"""Test suite for ComputeMesh Industrial Product & Price Comparison Engine."""

import json
import unittest
from services.mcp.builtin.product_price_engine import (
    search_product_prices,
    parse_numeric_price,
    extract_merchant_name,
)
from services.mcp.formatting.tool_formatter import format_tool_content_if_json
from services.mcp.intent.intent_router import detect_direct_tool_intent
from services.mcp.tool_registry import ToolRegistry


class TestProductPriceEngine(unittest.TestCase):
    def test_parse_numeric_price(self):
        self.assertEqual(parse_numeric_price("1.199,00 €"), 1199.0)
        self.assertEqual(parse_numeric_price("€ 1,249.99"), 1249.99)
        self.assertEqual(parse_numeric_price("ab 849.50 EUR"), 849.5)
        self.assertEqual(parse_numeric_price("1299"), 1299.0)
        self.assertEqual(parse_numeric_price(""), 0.0)

    def test_extract_merchant_name(self):
        self.assertEqual(extract_merchant_name("https://www.amazon.de/dp/B0CHX1W1XY"), "Amazon.de")
        self.assertEqual(extract_merchant_name("https://mindfactory.de/product_info.php/123"), "Mindfactory.de")
        self.assertEqual(extract_merchant_name("https://www.mediamarkt.de/de/product/123"), "MediaMarkt.de")
        self.assertEqual(extract_merchant_name(""), "Online-Händler")

    def test_search_product_prices_benchmark(self):
        res = search_product_prices("iPhone 16 Pro", country_code="DE")
        self.assertIn("product", res)
        self.assertIn("offers", res)
        self.assertTrue(res["total_offers"] > 0)
        self.assertTrue(res["best_price"] > 0)
        self.assertIsNotNone(res["best_deal"])
        self.assertEqual(res["currency"], "EUR")

        # Verify sorted ascending by total price
        prices = [offer["total_price"] for offer in res["offers"]]
        self.assertEqual(prices, sorted(prices))

        # Check best deal matches first offer
        self.assertEqual(res["best_deal"]["merchant"], res["offers"][0]["merchant"])

    def test_search_product_prices_fallback_generic(self):
        res = search_product_prices("Spezial Custom Gadget XYZ 9999", country_code="DE")
        self.assertIn("product", res)
        self.assertIn("offers", res)
        self.assertTrue(len(res["offers"]) >= 1)
        self.assertTrue(res["best_price"] > 0)

    def test_product_price_formatter_table(self):
        sample_data = {
            "price_comparison": True,
            "product": "iPhone 16 Pro 256GB Titan Natur",
            "currency": "EUR",
            "best_price": 1149.0,
            "max_price": 1299.0,
            "average_price": 1214.0,
            "savings_max": 150.0,
            "savings_percent": 11.5,
            "best_deal": {
                "merchant": "Amazon.de",
                "price": 1149.0,
                "shipping": 0.0,
                "total_price": 1149.0,
                "availability": "Auf Lager, lieferbar in 1-2 Werktagen",
                "rating": 4.8,
                "url": "https://www.amazon.de",
            },
            "offers": [
                {
                    "rank": 1,
                    "merchant": "Amazon.de",
                    "title": "Apple iPhone 16 Pro 256GB Titan Natur",
                    "price": 1149.0,
                    "shipping": 0.0,
                    "total_price": 1149.0,
                    "availability": "Auf Lager, lieferbar in 1-2 Werktagen",
                    "rating": 4.8,
                    "url": "https://www.amazon.de",
                },
                {
                    "rank": 2,
                    "merchant": "Mindfactory.de",
                    "title": "Apple iPhone 16 Pro 256GB",
                    "price": 1169.0,
                    "shipping": 4.99,
                    "total_price": 1173.99,
                    "availability": "Lagernd",
                    "rating": 4.7,
                    "url": "https://www.mindfactory.de",
                },
            ],
            "total_offers": 2,
        }
        formatted = format_tool_content_if_json(json.dumps(sample_data))
        self.assertIn("Preisvergleich: iPhone 16 Pro 256GB Titan Natur", formatted)
        self.assertIn("Bestpreis", formatted)
        self.assertIn("Amazon.de", formatted)
        self.assertIn("Mindfactory.de", formatted)
        self.assertIn("1,149.00 €", formatted)
        self.assertIn("150.00 € (11.5%)", formatted)

    def test_intent_router_product_price_detection(self):
        queries = [
            "Führe einen Preisvergleich für das iPhone 16 Pro 256GB durch und zeige die besten Händler-Angebote in einer Tabelle",
            "Was kostet eine Sony PlayStation 5 Pro aktuell im Preisvergleich?",
            "Günstigster Preis für AirPods Pro 2",
            "Vergleiche Preise für MacBook Pro M3 14 Zoll",
            "Finde die besten Angebote und Preise für RTX 4080 Super",
        ]
        for query in queries:
            match = detect_direct_tool_intent(query)
            self.assertIsNotNone(match, f"Failed to match query: {query}")
            tool_name, tool_args = match
            self.assertEqual(tool_name, "search_product_prices", f"Query routed to wrong tool {tool_name} for: {query}")
            prod_val = tool_args.get("query") or tool_args.get("product_query") or tool_args.get("product_name")
            self.assertTrue(bool(prod_val and len(prod_val) > 0))

    def test_tool_registry_registration(self):
        registry = ToolRegistry()
        tool_names = [t.name for t in registry.list_tools()]
        self.assertIn("search_product_prices", tool_names)


if __name__ == "__main__":
    unittest.main()
