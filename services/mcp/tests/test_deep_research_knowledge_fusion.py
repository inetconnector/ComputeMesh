# SPDX-License-Identifier: Apache-2.0
"""
Tests for Deep Multi-Source Knowledge Fusion, Cross-Lingual Wikipedia,
Conversational Context Resolution, and Fact Verification.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch, MagicMock

from services.mcp.agent_loop import AgentLoop, detect_direct_tool_intent, format_tool_content_if_json
from services.mcp.builtin.context_resolver import resolve_contextual_query, extract_dominant_topic
from services.mcp.builtin.multilingual_wiki import fetch_multilingual_wikipedia
from services.mcp.builtin.knowledge_fusion import cross_source_knowledge_search
from services.mcp.builtin.timeline_builder import fetch_recent_timeline
from services.mcp.builtin.fact_triangulation import verify_fact_multi_source
from services.mcp.config import MCPConfig
from services.mcp.tool_registry import ToolRegistry


class TestDeepResearchKnowledgeFusion(unittest.TestCase):
    def setUp(self):
        self.config = MCPConfig(system_tools_enabled=True)
        self.registry = ToolRegistry(self.config)
        self.loop = AgentLoop(registry=self.registry, config=self.config)

    def test_context_resolver_pronoun_extraction(self):
        messages = [
            {"role": "user", "content": "Erzähl mir über den Konflikt in Taiwan."},
            {"role": "assistant", "content": "Die **Taiwan-Krise** betrifft die geopolitische Lage in der Taiwanstraße zwischen China und Taiwan."},
            {"role": "user", "content": "was ist da als letztes passiert"},
        ]
        resolved_q, entity, was_resolved = resolve_contextual_query("was ist da als letztes passiert", messages)
        self.assertTrue(was_resolved)
        self.assertIsNotNone(entity)
        self.assertIn("Taiwan", entity)
        self.assertIn("aktuelle Ereignisse", resolved_q)

    def test_multilingual_wikipedia_mocked(self):
        with patch("services.mcp.builtin.multilingual_wiki._fetch_wiki_summary_by_title") as mock_fetch:
            mock_fetch.side_effect = lambda title, lang, timeout: {
                "title": title,
                "extract": f"Summary in {lang} for {title}",
                "url": f"https://{lang}.wikipedia.org/wiki/{title}",
                "language": lang,
            }
            res = fetch_multilingual_wikipedia("Quantum Computing")
            self.assertIn("title", res)
            self.assertIn("Wikipedia (Deutsch", res["extract"])
            self.assertIn("Wikipedia (English", res["extract"])
            self.assertGreaterEqual(len(res["sources"]), 2)

    def test_knowledge_fusion_triangulation(self):
        with patch("services.mcp.builtin.knowledge_fusion.fetch_multilingual_wikipedia") as mock_wiki, \
             patch("services.mcp.builtin.knowledge_fusion.execute_get_news") as mock_news, \
             patch("services.mcp.builtin.knowledge_fusion.duckduckgo_search") as mock_web:
            
            mock_wiki.return_value = {
                "title": "Künstliche Intelligenz",
                "extract": "KI ist ein Teilgebiet der Informatik.",
                "sources": ["https://de.wikipedia.org/wiki/KI"],
            }
            mock_news.return_value = {
                "articles": [
                    {"title": "Neue KI-Modelle vorgestellt", "link": "https://tagesschau.de/ki", "source": "Tagesschau", "published": "Heute"}
                ]
            }
            mock_web.return_value = [
                {"title": "KI Durchbruch", "url": "https://example.com/ki", "snippet": "Forscher melden Durchbruch."}
            ]

            res = cross_source_knowledge_search("Künstliche Intelligenz")
            self.assertEqual(res["status"], "success")
            self.assertIn("Enzyklopädischer Hintergrund", res["markdown"])
            self.assertIn("Aktuelle Nachrichten", res["markdown"])
            self.assertIn("Web-Recherche", res["markdown"])
            self.assertIn("Verifizierte Quellen", res["markdown"])

    def test_fetch_recent_timeline(self):
        with patch("services.mcp.builtin.timeline_builder.execute_get_news") as mock_news, \
             patch("services.mcp.builtin.timeline_builder.duckduckgo_search") as mock_web:
            
            mock_news.return_value = {
                "articles": [
                    {"title": "Gipfeltreffen eröffnet", "link": "https://news.de/1", "source": "DPA", "published": "14. Sept 2026", "summary": "Staatschefs beraten."}
                ]
            }
            mock_web.return_value = [
                {"title": "Abschlusserklärung verabschiedet", "url": "https://news.de/2", "snippet": "Vereinbarung unterzeichnet."}
            ]

            res = fetch_recent_timeline("Gipfeltreffen 2026")
            self.assertEqual(res["status"], "ok")
            self.assertGreaterEqual(res["total_events"], 1)
            self.assertIn("Chronologische Zeitleiste", res["markdown"])

    def test_verify_fact_multi_source(self):
        with patch("services.mcp.builtin.fact_triangulation.fetch_multilingual_wikipedia") as mock_wiki, \
             patch("services.mcp.builtin.fact_triangulation.duckduckgo_search") as mock_web:
            
            mock_wiki.return_value = {
                "title": "Lichtgeschwindigkeit",
                "extract": "Die Lichtgeschwindigkeit im Vakuum beträgt exakt 299.792.458 m/s.",
                "sources": ["https://de.wikipedia.org/wiki/Lichtgeschwindigkeit"],
            }
            mock_web.return_value = [
                {"title": "Physics Fact", "url": "https://physics.org", "snippet": "Speed of light is 299,792,458 m/s."}
            ]

            res = verify_fact_multi_source("Die Lichtgeschwindigkeit beträgt knapp 300.000 km/s")
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["is_corroborated"])
            self.assertIn("Multi-Source Faktenprüfung", res["markdown"])

    def test_direct_intent_deep_research_and_context(self):
        intent_research = detect_direct_tool_intent("Recherchiere über die Geschichte der Raumfahrt")
        self.assertIsNotNone(intent_research)
        self.assertEqual(intent_research[0], "cross_source_knowledge_search")

        intent_timeline = detect_direct_tool_intent("Zeitleiste zum Nahostkonflikt")
        self.assertIsNotNone(intent_timeline)
        self.assertEqual(intent_timeline[0], "fetch_recent_timeline")

        intent_fact = detect_direct_tool_intent("Stimmt es dass der Mount Everest 8848 Meter hoch ist?")
        self.assertIsNotNone(intent_fact)
        self.assertEqual(intent_fact[0], "verify_fact_multi_source")


if __name__ == "__main__":
    unittest.main()
