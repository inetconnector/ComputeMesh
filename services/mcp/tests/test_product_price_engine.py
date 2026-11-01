# SPDX-License-Identifier: Apache-2.0
"""Test suite for ComputeMesh Industrial Product & Price Comparison Engine."""

import json
import unittest
from unittest.mock import patch

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
        # The destination hostname must not be confused with a merchant's name.
        self.assertEqual(
            extract_merchant_name("https://amazon.de.evil.example.org/item"),
            "amazon.de.evil.example.org",
        )
        self.assertEqual(
            extract_merchant_name("javascript:alert(1)", "Amazon genuine sale"),
            "Online-Händler",
        )

    def test_invalid_input_never_launches_search(self):
        bad_cases = (
            ({"query": ""}, "invalid_query"),
            ({"query": "?"}, "invalid_query"),
            ({"query": "..."}, "invalid_query"),
            ({"query": "x" * 241}, "invalid_query"),
            ({"query": ["not a string"]}, "invalid_query"),
            ({"query": "Laptop", "max_offers": True}, "invalid_argument"),
            ({"query": "Laptop", "max_offers": 0}, "invalid_argument"),
            ({"query": "Laptop", "max_offers": 11}, "invalid_argument"),
            ({"query": "Laptop", "max_offers": "5"}, "invalid_argument"),
            ({"query": "Laptop", "timeout": 0}, "invalid_argument"),
            ({"query": "Laptop", "timeout": 99}, "invalid_argument"),
            ({"query": "Laptop", "country_code": "CH"}, "unsupported"),
            ({"query": "Laptop", "country_code": "AT"}, "unsupported"),
            ({"query": "Laptop", "sort_by": "rating"}, "unsupported"),
        )
        with patch(
            "services.mcp.builtin.product_price_engine.fetch_live_shopping_offers"
        ) as fetch:
            for arguments, expected_status in bad_cases:
                with self.subTest(arguments=arguments):
                    result = search_product_prices(**arguments)
                    self.assertEqual(result["status"], expected_status)
                    self.assertEqual(result["offers"], [])
                    self.assertIsNone(result["best_price"])
                    self.assertFalse(result["price_comparison"])
                    display = format_tool_content_if_json(json.dumps(result))
                    self.assertIn(result["error"], display)
            fetch.assert_not_called()

    def test_search_response_limit_fails_closed(self):
        from services.mcp.builtin.product_price_engine import fetch_live_shopping_offers

        with patch(
            "services.mcp.builtin.product_price_engine.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = b"x" * 2_000_001
            hits = fetch_live_shopping_offers("Gerät")
            self.assertEqual(hits, [])
            mock_open.return_value.__enter__.return_value.read.assert_called_once_with(2_000_001)

    def test_tool_description_never_claims_live_verified_prices(self):
        registry = ToolRegistry()
        tool = registry.get_tool("search_product_prices")
        self.assertIsNotNone(tool)
        self.assertIn("unverifizierte", tool.description)
        self.assertNotIn("Bestpreis, Durchschnittspreis und Ersparnispotenziale", tool.description)
        self.assertEqual(tool.parameters["properties"]["country"]["enum"], ["DE"])

    def test_unverified_search_snippets_are_not_confirmed_offers(self):
        search_hit = {
            "merchant": "Example Shop",
            "price": 199.0,
            "currency": "EUR",
            "shipping": "Unbekannt",
            "availability": "Nicht verifiziert",
            "url": "https://example.org/item",
        }
        with patch(
            "services.mcp.builtin.product_price_engine.fetch_live_shopping_offers",
            return_value=[search_hit],
        ):
            res = search_product_prices("Beispielgerät", country_code="DE")
        self.assertEqual(res["status"], "unverified")
        self.assertEqual(res["data_quality"], "search_snippet_unverified")
        self.assertFalse(res["price_comparison"])
        # Fields normally used for verified quotations must not carry estimates.
        self.assertIsNone(res["best_price"])
        self.assertIsNone(res["best_deal"])
        self.assertIsNone(res["best_merchant"])
        self.assertIsNone(res["average_price"])
        self.assertEqual(res["unverified_lowest_price"], 199.0)
        self.assertEqual(res["total_offers"], 1)
        self.assertEqual(res["offers"][0]["price"], 199.0)
        self.assertIsNone(res["offers"][0]["total_price"])
        self.assertFalse(res["offers"][0]["verified"])
        self.assertNotIn("rating", res["offers"][0])
        self.assertIsNone(res["savings_max"])
        rendered = format_tool_content_if_json(json.dumps(res))
        self.assertIn("Nicht verifiziert", rendered)
        self.assertIn("Example Shop", rendered)
        self.assertNotIn("Kaufempfehlung:", rendered)
        self.assertNotIn("🏆 **Bestpreis:**", rendered)


    def test_four_digit_euro_prices_are_not_truncated(self):
        from services.mcp.builtin.product_price_engine import fetch_live_shopping_offers

        for title, expected in (
            ("Produkt 1199,99 EUR", 1199.99),
            ("Produkt € 2499,00", 2499.0),
        ):
            html_page = (
                '<a class="result__a" href="https://example.org/p">' + title + "</a>"
                '<a class="result__snippet" href="#">Artikel</a>'
            ).encode("utf-8")
            with self.subTest(title=title), patch(
                "services.mcp.builtin.product_price_engine.urllib.request.urlopen"
            ) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = html_page
                hits = fetch_live_shopping_offers("Produkt")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["price"], expected)

    def test_invalid_upstream_prices_never_become_offer_hints(self):
        safe = {
            "merchant": "Example Shop",
            "price": 219.0,
            "url": "https://shop.example.org/product",
        }
        bad = [
            {**safe, "price": True},
            {**safe, "price": float("nan")},
            {**safe, "price": float("inf")},
            {**safe, "price": float("-inf")},
            {**safe, "price": -2},
            {**safe, "price": 0},
            {**safe, "price": 10 ** 400},
            {**safe, "price": "219.0"},
            {**safe, "price": 1.0},
            {**safe, "price": 25_001.0},
            {**safe, "currency": "USD"},
            {**safe, "url": "https://127.0.0.1/admin"},
            {**safe, "url": "javascript:alert(1)"},
            {**safe, "url": ""},
            {"merchant": "No URL", "price": 219.0},
            "invalid upstream value",
            None,
        ]
        with patch(
            "services.mcp.builtin.product_price_engine.fetch_live_shopping_offers",
            return_value=bad + [safe],
        ):
            result = search_product_prices("Beispielgerät", country_code="DE")
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["total_offers"], 1)
        self.assertEqual(result["unverified_lowest_price"], 219.0)
        self.assertEqual(result["offers"][0]["price"], 219.0)
        self.assertFalse(result["offers"][0]["verified"])
        self.assertNotIn("verified", safe, "do not mutate untrusted upstream dict")
        self.assertEqual(result["offers"][0]["availability"], "Nicht verifiziert")
        self.assertEqual(result["offers"][0]["shipping"], "Unbekannt")
        self.assertNotIn("stock", result["offers"][0])
        self.assertNotIn("rating", result["offers"][0])

        with patch(
            "services.mcp.builtin.product_price_engine.fetch_live_shopping_offers",
            return_value=bad,
        ):
            empty_result = search_product_prices("Beispielgerät", country_code="DE")
        self.assertEqual(empty_result["status"], "unavailable")
        self.assertEqual(empty_result["offers"], [])
        self.assertIsNone(empty_result["best_price"])

    def test_upstream_stock_and_ratings_claims_never_survive_normalization(self):
        unverified = {
            "merchant": "Example Merchant",
            "price": 99.0,
            "url": "https://shop.example.org/item",
            "currency": "EUR",
            "availability": "Auf Lager",
            "shipping": "0,00 €",
            "rating": 5.0,
            "stock": 999,
            "verified": True,
            "best_price": 99.0,
            "savings_percent": 99.0,
        }
        with patch(
            "services.mcp.builtin.product_price_engine.fetch_live_shopping_offers",
            return_value=[unverified],
        ):
            result = search_product_prices("Beispielartikel", country_code="DE")
        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["best_price"])
        self.assertIsNone(result["savings_percent"])
        offer = result["offers"][0]
        self.assertFalse(offer["verified"])
        self.assertEqual(offer["availability"], "Nicht verifiziert")
        self.assertEqual(offer["shipping"], "Unbekannt")
        for claim in ("rating", "stock", "best_price", "savings_percent"):
            self.assertNotIn(claim, offer)
        self.assertTrue(unverified["verified"], "do not mutate upstream objects")

    def test_formatter_omits_nan_infinite_bool_and_huge_numeric_hints(self):
        data = {
            "status": "unverified",
            "data_quality": "search_snippet_unverified",
            "product_name": "Beispielgerät",
            "offers": [
                {"merchant": "Safe", "price": 219.0, "url": "https://shop.example.org/item"},
                {"merchant": "Bool", "price": True},
                {"merchant": "NaN", "price": float("nan")},
                {"merchant": "Infinity", "price": float("inf")},
                {"merchant": "Giant", "price": 10 ** 400},
                {"merchant": "Zero", "price": 0},
                {"merchant": "Negative", "price": -1},
                {"merchant": "String", "price": "1.0"},
                "malformed",
            ],
        }
        rendered = format_tool_content_if_json(json.dumps(data))
        self.assertIn("Safe", rendered)
        self.assertIn("219.00 €", rendered)
        for invalid in ("Bool", "NaN", "Infinity", "Giant", "Zero", "Negative", "String"):
            self.assertNotIn("| " + invalid + " |", rendered)
        self.assertEqual(rendered.count("[Suchtreffer]("), 1)

    def test_legacy_benchmark_helper_returns_no_fabricated_shops(self):
        from services.mcp.builtin.product_price_engine import get_curated_benchmark_offers

        for query in ("iPhone 16 Pro", "Samsung Galaxy S24 Ultra", "RTX 4090"):
            with self.subTest(query=query):
                self.assertEqual(get_curated_benchmark_offers(query), [])

    def test_no_results_never_fabricate_benchmarks_or_generic_merchants(self):
        with patch(
            "services.mcp.builtin.product_price_engine.fetch_live_shopping_offers",
            return_value=[],
        ):
            for query in ("iPhone 16 Pro", "Spezial Custom Gadget XYZ 9999"):
                with self.subTest(query=query):
                    res = search_product_prices(query, country_code="DE")
                    self.assertEqual(res["status"], "unavailable")
                    self.assertEqual(res["data_quality"], "no_live_offers")
                    self.assertFalse(res["price_comparison"])
                    self.assertEqual(res["offers"], [])
                    self.assertEqual(res["total_offers"], 0)
                    self.assertIsNone(res["best_price"])
                    self.assertIsNone(res["best_deal"])
                    self.assertIsNone(res["average_price"])
                    rendered = format_tool_content_if_json(json.dumps(res))
                    self.assertIn("Keine aktuellen Preisangaben", rendered)
                    self.assertNotIn("Kaufempfehlung", rendered)

    def test_scraper_leaves_stock_shipping_and_rating_unconfirmed(self):
        from services.mcp.builtin.product_price_engine import fetch_live_shopping_offers

        html_snippet = (
            '<a class="result__a" href="https://example.org/item">Gerät 219 €</a>'
            '<a class="result__snippet" href="https://example.org/item">Top Gerät</a>'
        ).encode("utf-8")
        with patch(
            "services.mcp.builtin.product_price_engine.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = html_snippet
            hits = fetch_live_shopping_offers("Gerät")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["price"], 219.0)
        self.assertEqual(hits[0]["shipping"], "Unbekannt")
        self.assertEqual(hits[0]["availability"], "Nicht verifiziert")
        self.assertFalse(hits[0]["verified"])
        self.assertNotIn("rating", hits[0])

    def test_usd_snippets_are_not_silently_relabelled_as_eur(self):
        from services.mcp.builtin.product_price_engine import fetch_live_shopping_offers

        html_snippet = (
            '<a class="result__a" href="https://example.org/item">Device $1,299.00</a>'
            '<a class="result__snippet" href="https://example.org/item">Sale</a>'
        ).encode("utf-8")
        with patch(
            "services.mcp.builtin.product_price_engine.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = html_snippet
            hits = fetch_live_shopping_offers("Device")
        self.assertEqual(hits, [])


    def test_scraper_ignores_unsafe_url_and_unknown_merchant_identity(self):
        from services.mcp.builtin.product_price_engine import fetch_live_shopping_offers

        html_snippet = (
            '<a class="result__a" href="javascript:alert(1)">Fake Gerät 179 €</a>'
            '<a class="result__snippet" href="#">Fake</a>'
            '<a class="result__a" href="https://amazon.de.evil.example.org/item">'
            'Fake Gerät 199 €</a>'
            '<a class="result__snippet" href="#">Angebot</a>'
        ).encode("utf-8")
        with patch(
            "services.mcp.builtin.product_price_engine.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = html_snippet
            hits = fetch_live_shopping_offers("Fake Gerät")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["merchant"], "amazon.de.evil.example.org")
        self.assertEqual(hits[0]["price"], 199.0)
        self.assertFalse(hits[0]["verified"])

    def test_internal_dns_suffixes_are_rejected_before_snippet_ingestion(self):
        from services.mcp.builtin.product_price_engine import fetch_live_shopping_offers

        blocked = (
            "https://shop.local/item",
            "https://shop.lan/item",
            "https://shop.home.arpa/item",
            "https://shop.internal/item",
            "https://shop.corp/item",
            "https://shop.test/item",
            "https://shop.example/item",
            "https://shop.onion/item",
            "https://shop.example.org./item",
            "https://-shop.example.org/item",
            "https://shop-.example.org/item",
        )
        for url in blocked:
            with self.subTest(url=url):
                self.assertEqual(extract_merchant_name(url), "Online-Händler")

        parts = [
            (
                '<a class="result__a" href="' + url + '">Gerät 219 €</a>'
                '<a class="result__snippet" href="#">Preisangabe</a>'
            )
            for url in blocked
        ]
        parts.append(
            '<a class="result__a" href="https://shop.example.org/item">Gerät 219 €</a>'
            '<a class="result__snippet" href="#">Preisangabe</a>'
        )
        with patch(
            "services.mcp.builtin.product_price_engine.urllib.request.urlopen"
        ) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = (
                "".join(parts).encode("utf-8")
            )
            hits = fetch_live_shopping_offers("Gerät")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["url"], "https://shop.example.org/item")
        self.assertFalse(hits[0]["verified"])

    def test_unverified_and_empty_results_escape_untrusted_markdown(self):
        for status, details in (
            ("unavailable", {}),
            ("invalid_query", {"error": "Invalid [click](https://evil.example.org)"}),
        ):
            with self.subTest(status=status):
                data = {
                    "status": status,
                    "data_quality": "no_live_offers",
                    "product_name": "Unsafe [CLICK](https://evil.example.org)",
                    **details,
                }
                rendered = format_tool_content_if_json(json.dumps(data))
                self.assertIn(r"\[CLICK\]", rendered)
                self.assertNotIn("[CLICK](https://evil.example.org)", rendered)
                if "error" in details:
                    self.assertIn(r"\[click\]", rendered)
                    self.assertNotIn("[click](https://evil.example.org)", rendered)

    def test_untrusted_merchant_text_cannot_break_markdown_table(self):
        data = {
            "status": "unverified",
            "data_quality": "search_snippet_unverified",
            "product_name": "Phone",
            "offers": [{
                "merchant": "Fake | [CLICK](https://evil.example.org)",
                "price": 123.0,
                "shipping": "Unbekannt",
                "availability": "Nicht verifiziert",
                "url": "javascript:alert(1)",
            }],
        }
        formatted = format_tool_content_if_json(json.dumps(data))
        self.assertIn(r"Fake \| \[CLICK\]", formatted)
        self.assertIn("Keine Quelle", formatted)
        self.assertNotIn("[Suchtreffer](javascript:", formatted)

    def test_unverified_snippet_links_reject_internal_and_ambiguous_urls(self):
        # Displaying a URL is not authorization to fetch it. Reject link targets
        # that could be local, malformed or carry embedded credentials.
        blocked_urls = (
            "https://localhost/admin",
            "https://127.0.0.1/admin",
            "https://192.168.1.1/private",
            "https://[::1]/private",
            "https://shop.local/internal",
            "https://shop.internal/status",
            "https://shop.onion/hidden",
            "https://shop.localdomain/admin",
            "https://shop.example.org./item",
            "https://-shop.example.org/item",
            "https://shop-.example.org/item",
            "https://shop.example.org:8443/private",
            "https://user:password@shop.example.org/order",
            "https://shop.example.org@127.0.0.1/",
            "http://shop.example.org/item",
            "javascript:alert(1)",
            "https://shop.example.org\\@127.0.0.1/",
        )
        for url in blocked_urls:
            with self.subTest(url=url):
                data = {
                    "status": "unverified",
                    "data_quality": "search_snippet_unverified",
                    "product_name": "Example item",
                    "offers": [{"merchant": "Example Shop", "price": 123.0, "url": url}],
                }
                rendered = format_tool_content_if_json(json.dumps(data))
                self.assertIn("Keine Quelle", rendered)
                self.assertNotIn("[Suchtreffer](", rendered)

        valid_data = {
            "status": "unverified",
            "data_quality": "search_snippet_unverified",
            "product_name": "Example item",
            "offers": [{
                "merchant": "Example Shop",
                "price": 123.0,
                "url": "https://shop.example.org/item?color=blue",
            }],
        }
        valid_rendered = format_tool_content_if_json(json.dumps(valid_data))
        self.assertIn(
            "[Suchtreffer](https://shop.example.org/item?color=blue)",
            valid_rendered,
        )

        # A closing parenthesis from an untrusted URL must not break Markdown.
        valid_data["offers"][0]["url"] = "https://shop.example.org/a)"
        escaped_link = format_tool_content_if_json(json.dumps(valid_data))
        self.assertIn("[Suchtreffer](https://shop.example.org/a%29)", escaped_link)
        self.assertNotIn("[Suchtreffer](https://shop.example.org/a))", escaped_link)

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