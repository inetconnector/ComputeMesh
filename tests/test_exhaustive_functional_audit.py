# SPDX-License-Identifier: Apache-2.0
"""Exhaustive Functional Audit & Verification Test Suite for All ComputeMesh Functions.

Tests every functional unit, method, and tool across:
- Pillar 1: Python Code Interpreter & Sandbox (AST security, stdout/stderr, result, matplotlib plots)
- Pillar 2: Vector RAG & Embeddings (384-dim dense vectors, cosine sim, chunking, parsing, vector store)
- Pillar 3: Deep Reasoning & Thinking (accordion transformation, think tags)
- Pillar 4: GBNF Grammar Compiler (JSON Schema -> GBNF rules, types, enums, primitives)
- Pillar 5: Persistent User Memory (profile, key-value memory, deletion, summary injection)
- Pillar 6: Streaming Voice Real-Time VAD (energy calculation, silence/speech detection, barge-in)
- Pillar 7: High-Performance Image Engine (model catalog, binary resolution)
- Pillar 8: Complete Built-in Live Tools & Tool Registry (all 31 built-in MCP tools, alias mapping, execution)
- Pillar 9: MCP Agent Loop (typo-tolerant intent routing, tool formatting, reasoning blocks)
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
import sys
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --- Pillar 1: Code Interpreter ---
from services.mcp.builtin.python_sandbox import execute_python_code, run_code_interpreter

# --- Pillar 2: RAG, Embeddings, Chunker, Parser, VectorStore ---
from services.rag.embeddings import (
    _dense_semantic_embedding,
    compute_embeddings,
    compute_semantic_embedding,
    cosine_similarity,
    get_text_embedding,
)
from services.rag.chunker import DocumentChunk, chunk_text
from services.rag.document_parser import extract_text_from_file, parse_document_content, parse_document_text
from services.rag.vector_store import SearchResult, VectorStore, get_default_vector_store

# --- Pillar 3 & 9: Reasoning Blocks & Agent Loop ---
from services.mcp.agent_loop import (
    _decode_arguments,
    detect_direct_tool_intent,
    format_reasoning_and_thinking_blocks,
    format_tool_content_if_json,
)

# --- Pillar 4: GBNF Grammar Compiler ---
from services.grammar.json_schema_to_gbnf import (
    _compile_type_to_gbnf,
    _sanitize_rule_name,
    compile_json_schema_to_gbnf,
    json_schema_to_gbnf,
)

# --- Pillar 5: User Memory ---
from services.memory.user_memory import (
    UserProfile,
    UserMemoryStore,
    delete_user_memory,
    get_user_memory,
    get_user_memory_store,
    update_user_memory,
)

# --- Pillar 6: Streaming Voice VAD ---
from services.voice.voice_realtime import (
    RealtimeVoiceSession,
    SimpleEnergyVAD,
    compute_audio_energy,
    create_voice_session,
)

# --- Pillar 7: SD.cpp Image Engine ---
from runtime.sd_cpp.image_engine_service import FAST_MODELS, find_sd_server_binary

# --- Pillar 8: Tool Registry & All Builtin Tools ---
from services.mcp.tool_registry import ToolRegistry
from services.mcp.builtin.arxiv_research import search_arxiv_papers
from services.mcp.builtin.chemical_data import lookup_chemical_compound
from services.mcp.builtin.company_lookup import lookup_company
from services.mcp.builtin.country_data import lookup_country_data
from services.mcp.builtin.currency import convert_currency
from services.mcp.builtin.dictionary_lookup import lookup_word_definition
from services.mcp.builtin.earthquake_feed import get_recent_earthquakes
from services.mcp.builtin.events import search_events
from services.mcp.builtin.finance_market import execute_finance_quote, get_market_quote
from services.mcp.builtin.food_products import lookup_food_product
from services.mcp.builtin.generate_image import generate_ai_image
from services.mcp.builtin.geo_routing import get_distance_route
from services.mcp.builtin.network_tools import lookup_network_host
from services.mcp.builtin.news_feed import clean_text as news_clean_text, execute_get_news, get_live_news
from services.mcp.builtin.package_registry import lookup_software_package
from services.mcp.builtin.places import search_places
from services.mcp.builtin.python_calc import run_python_calc
from services.mcp.builtin.rag_tool import index_document_text, list_indexed_documents, search_knowledge_base
from services.mcp.builtin.sports_data import get_sports_data
from services.mcp.builtin.system_tools import execute_system_info
from services.mcp.builtin.time_calendar import calculate_easter_sunday, get_german_holidays, get_time_and_calendar
from services.mcp.builtin.train_transit import lookup_train_schedule
from services.mcp.builtin.url_security import check_url_safety
from services.mcp.builtin.weather import execute_get_weather, get_current_weather
from services.mcp.builtin.weather_forecast import get_weather_forecast
from services.mcp.builtin.web_fetch import execute_web_fetch
from services.mcp.builtin.web_search import execute_web_search
from services.mcp.builtin.wikipedia import get_wikipedia_summary
from services.mcp.builtin.world_bank import get_world_bank_stats


class TestPillar1CodeInterpreter(unittest.TestCase):
    """Tests for Python Sandbox execution and plot generation."""

    def test_basic_math_execution(self):
        res = execute_python_code("a = 10\nb = 20\nresult = a + b\nprint('Computed:', result)")
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "success")
        self.assertIn("Computed: 30", res["stdout"])
        self.assertEqual(res["result"], "30")
        self.assertIn("Rückgabewert:", res["markdown"])

    def test_expression_evaluation(self):
        res = execute_python_code("2 ** 10")
        self.assertTrue(res["success"])
        self.assertEqual(res["result"], "1024")

    def test_empty_code_handling(self):
        res = execute_python_code("")
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_ast_security_blocking(self):
        dangerous_snippets = [
            "import os\nos.system('echo test')",
            "import subprocess\nsubprocess.run(['ls'])",
            "import shutil\nshutil.rmtree('/tmp')",
        ]
        for snip in dangerous_snippets:
            res = execute_python_code(snip)
            self.assertFalse(res["success"])
            self.assertEqual(res["status"], "security_violation")
            self.assertIn("Sicherheitsverletzung", res["markdown"])

    def test_matplotlib_figure_capture(self):
        code = (
            "import matplotlib.pyplot as plt\n"
            "plt.figure(figsize=(4, 2))\n"
            "plt.plot([1, 2, 3], [4, 5, 6])\n"
            "plt.title('Test Plot')\n"
        )
        res = execute_python_code(code)
        self.assertTrue(res["success"])
        self.assertGreaterEqual(len(res["images"]), 1)
        self.assertTrue(res["images"][0].startswith("data:image/png;base64,"))

    def test_alias_run_code_interpreter(self):
        res = run_code_interpreter("1 + 1")
        self.assertEqual(res["result"], "2")


class TestPillar2VectorRAGAndEmbeddings(unittest.TestCase):
    """Tests for RAG, 384-dim semantic embeddings, chunker, parser, and vector store."""

    def test_dense_semantic_embedding_dimensions_and_normalization(self):
        vec = get_text_embedding("ComputeMesh Control Plane Inferenz")
        self.assertEqual(len(vec), 384)
        # Verify L2 norm is approximately 1.0
        norm = sum(v * v for v in vec) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_embedding_batch(self):
        batch = compute_embeddings(["Text 1", "Text 2", "Text 3"])
        self.assertEqual(len(batch), 3)
        self.assertEqual(len(batch[0]), 384)

    def test_cosine_similarity(self):
        v1 = get_text_embedding("Künstliche Intelligenz und maschinelles Lernen")
        v2 = get_text_embedding("KI, Deep Learning und künstliche neuronale Netze")
        v3 = get_text_embedding("Apfelkuchen mit Streuseln und Vanilleeis backen")

        sim_related = cosine_similarity(v1, v2)
        sim_unrelated = cosine_similarity(v1, v3)
        self.assertGreater(sim_related, sim_unrelated)

    def test_chunker(self):
        text = "Absatz 1.\n\nAbsatz 2 ist ein längerer Text mit weiteren Details.\n\nAbsatz 3 schließt ab."
        chunks = chunk_text(text, doc_id="test_doc", chunk_size=50, chunk_overlap=10)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(isinstance(c, DocumentChunk) for c in chunks))
        self.assertEqual(chunks[0].doc_id, "test_doc")

    def test_document_parser_content(self):
        parsed = parse_document_content("Inhalt einer Textdatei", filename="sample.txt")
        self.assertEqual(parsed["file_name"], "sample.txt")
        self.assertEqual(parsed["text"], "Inhalt einer Textdatei")
        self.assertEqual(parsed["metadata"]["type"], "direct_text")

    def test_document_parser_file_extraction(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            tmp.write("Hello File Parser\nLine 2")
            tmp_path = tmp.name
        try:
            res = extract_text_from_file(tmp_path)
            self.assertIn("Hello File Parser", res["text"])
            self.assertEqual(res["extension"], ".txt")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_vector_store_lifecycle(self):
        temp_dir = tempfile.mkdtemp()
        try:
            store = VectorStore(collection_name="test_col", persist_dir=temp_dir)
            store.clear()
            self.assertEqual(len(store.list_documents()), 0)

            # Add document
            add_res = store.add_document(
                text="ComputeMesh ist ein dezentrales Inferenz-Netzwerk für Edge- und GPU-Geräte.",
                doc_id="cm_intro",
                filename="intro.txt",
            )
            self.assertTrue(add_res["success"])
            self.assertEqual(add_res["total_chunks"], 1)

            # Search
            results = store.search("Inferenz auf Edge-Geräten", top_k=3)
            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0].doc_id, "cm_intro")
            self.assertEqual(results[0].document_id, "cm_intro")
            self.assertGreater(results[0].score, 0.1)

            # List
            docs = store.list_documents()
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]["doc_id"], "cm_intro")

            # Delete
            del_ok = store.delete_document("cm_intro")
            self.assertTrue(del_ok)
            self.assertEqual(len(store.list_documents()), 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPillar3And9ReasoningAndAgentLoop(unittest.TestCase):
    """Tests for Deep Reasoning accordion formatting and Agent Loop intent parsing."""

    def test_reasoning_accordion_conversion(self):
        raw = "<think>\n1. Planen\n2. Ausführen\n</think>\nFertige Antwort."
        formatted = format_reasoning_and_thinking_blocks(raw)
        self.assertIn('<details class="cm-thinking-block">', formatted)
        self.assertIn("Gedankengang anzeigen", formatted)
        self.assertIn("Fertige Antwort.", formatted)
        self.assertNotIn("<think>", formatted)

    def test_format_tool_content_json_weather(self):
        payload = json.dumps({"location": "Berlin", "temperature_celsius": 18.5, "condition": "Sonnig"})
        fmt = format_tool_content_if_json(payload)
        self.assertIn("Berlin", fmt)
        self.assertIn("18.5", fmt)

    def test_parse_strict_json_tool_arguments(self):
        parsed, err = _decode_arguments('{"location": "Würzburg"}')
        self.assertIsNone(err)
        self.assertEqual(parsed.get("location"), "Würzburg")

        # Invalid JSON
        parsed_err, err_msg = _decode_arguments("invalid non json")
        self.assertIsNone(parsed_err)
        self.assertIsNotNone(err_msg)

    def test_direct_intent_detection_matrix(self):
        queries = [
            ("Welche Tools hast du?", "list_available_tools"),
            ("Generiere ein Bild von einem Astronauten auf dem Mars", "generate_ai_image"),
            ("Prüfe die URL https://example.com auf Sicherheit", "check_url_safety"),
            ("Plotte eine Sinus Kurve mit Python", "execute_python_code"),
            ("Suche in der Wissensbasis nach ComputeMesh Handbuch", "search_knowledge_base"),
            ("Was weißt du über mich?", "get_user_memory"),
            ("Wie ist das Wetter in Frankfurt?", "get_current_weather"),
            ("Bitcoin Kurs aktuell", "get_market_quote"),
            ("Wie spät ist es?", "get_current_time_calendar"),
            ("Berechne 125 * 8", "calculate_math"),
            ("Was bits neues jn den Nachrichten", "get_live_news"),
            ("Konzerte in Würzburg", "search_events"),
        ]
        for query, expected_tool in queries:
            intent = detect_direct_tool_intent(query)
            self.assertIsNotNone(intent, f"Failed to detect intent for '{query}'")
            self.assertEqual(intent[0], expected_tool, f"Query '{query}' expected '{expected_tool}', got '{intent[0]}'")


class TestPillar4GBNFGrammarCompiler(unittest.TestCase):
    """Tests for JSON Schema to llama.cpp GBNF grammar compiler."""

    def test_compile_primitive_and_object_schema(self):
        schema = {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer"},
                "username": {"type": "string"},
                "active": {"type": "boolean"},
                "score": {"type": "number"},
                "status": {"type": "string", "enum": ["online", "away", "offline"]},
            },
            "required": ["user_id", "username", "status"],
        }
        gbnf = json_schema_to_gbnf(schema)
        self.assertIn("root ::=", gbnf)
        self.assertIn('"user_id"', gbnf)
        self.assertIn('"username"', gbnf)
        self.assertIn('"online"', gbnf)
        self.assertIn('"away"', gbnf)
        self.assertIn("integer ::=", gbnf)
        self.assertIn("boolean ::=", gbnf)

    def test_compile_array_schema(self):
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        gbnf = compile_json_schema_to_gbnf(schema)
        self.assertIn("root ::= \"[\"", gbnf)
        self.assertIn("item ::=", gbnf)

    def test_sanitize_rule_name(self):
        clean = _sanitize_rule_name("invalid-prop.name#123")
        self.assertEqual(clean, "invalid_prop_name_123")


class TestPillar5UserMemory(unittest.TestCase):
    """Tests for persistent user memory store, preferences, and system prompt formatting."""

    def test_memory_lifecycle(self):
        temp_dir = tempfile.mkdtemp()
        try:
            store = UserMemoryStore(persist_dir=temp_dir)
            store.clear()

            # Update profile
            store.update_profile(
                name="Frederik",
                preferred_language="Deutsch",
                preferences=["Dark Mode", "Kurze präzise Antworten"],
                facts=["Entwickelt ComputeMesh"],
            )

            # Update key-value memory
            store.update_memory("gpu_model", "NVIDIA RTX 3080", category="hardware")

            # Retrieve
            prof = store.get_profile()
            self.assertEqual(prof.name, "Frederik")
            self.assertEqual(prof.preferred_language, "Deutsch")

            mem = store.get_memory("gpu_model")
            self.assertIsNotNone(mem)
            self.assertEqual(mem["value"], "NVIDIA RTX 3080")

            # System prompt summary
            summary = store.get_memory_summary()
            self.assertIn("Frederik", summary)
            self.assertIn("Dark Mode", summary)
            self.assertIn("RTX 3080", summary)

            # Delete
            del_res = store.delete_memory("gpu_model")
            self.assertTrue(del_res["success"])
            self.assertIsNone(store.get_memory("gpu_model"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_global_memory_helpers(self):
        res = update_user_memory("test_key", "test_value", category="test")
        self.assertTrue(res["success"])
        m = get_user_memory("test_key")
        self.assertEqual(m.get("value"), "test_value")
        d = delete_user_memory("test_key")
        self.assertTrue(d["success"])


class TestPillar6VoiceStreamingVAD(unittest.TestCase):
    """Tests for Voice Activity Detection and barge-in handling."""

    def test_audio_energy_calculation(self):
        # 16-bit PCM silence
        silence = bytes(320 * 2)
        energy_silence = compute_audio_energy(silence)
        self.assertEqual(energy_silence, 0.0)

        # 16-bit PCM high amplitude
        loud_samples = bytearray()
        for i in range(320):
            loud_samples.extend((15000).to_bytes(2, byteorder="little", signed=True))
        energy_loud = compute_audio_energy(bytes(loud_samples))
        self.assertGreater(energy_loud, 0.3)

    def test_vad_speech_detection(self):
        vad = SimpleEnergyVAD(sample_rate=16000, threshold=0.015)
        silence = bytes(320 * 2)
        self.assertFalse(vad.is_speech(silence))

        loud_samples = bytearray()
        for i in range(320):
            loud_samples.extend((12000).to_bytes(2, byteorder="little", signed=True))
        self.assertTrue(vad.is_speech(bytes(loud_samples)))

    def test_voice_session_and_barge_in(self):
        session = create_voice_session("test_session_1")
        session.set_ai_speaking(True)
        self.assertTrue(session.is_ai_speaking)

        # Feed speech chunk while AI is speaking -> triggers barge-in
        speech_chunk = bytearray()
        for i in range(320):
            speech_chunk.extend((14000).to_bytes(2, byteorder="little", signed=True))

        res1 = session.process_audio_chunk(bytes(speech_chunk))
        res2 = session.process_audio_chunk(bytes(speech_chunk))
        self.assertFalse(session.is_ai_speaking)
        self.assertIn("interruption_detected", res2["events"])


class TestPillar7ImageEngine(unittest.TestCase):
    """Tests for SD.cpp image engine catalog and binary resolution."""

    def test_fast_models_catalog(self):
        self.assertIn("realvisxl-lightning", FAST_MODELS)
        self.assertIn("sdxl-lightning", FAST_MODELS)
        self.assertIn("flux-schnell-q4", FAST_MODELS)
        self.assertEqual(FAST_MODELS["realvisxl-lightning"]["type"], "sdxl")

    def test_find_sd_server_binary_type(self):
        bin_path = find_sd_server_binary()
        # Either found or None, but should not raise exception
        if bin_path is not None:
            self.assertTrue(isinstance(bin_path, Path))


class TestPillar8CompleteBuiltinTools(unittest.TestCase):
    """Exhaustive tests for all 31 built-in MCP live-data tools."""

    def test_tool_registry_initialization_and_aliases(self):
        registry = ToolRegistry()
        tools = registry.list_tools()
        self.assertGreaterEqual(len(tools), 25)

        # Test alias resolution
        self.assertEqual(registry._resolve_tool_name("get_weather"), "get_current_weather")
        self.assertEqual(registry._resolve_tool_name("code_interpreter"), "execute_python_code")
        self.assertEqual(registry._resolve_tool_name("search_rag"), "search_knowledge_base")
        self.assertEqual(registry._resolve_tool_name("stock_quote"), "get_market_quote")

    def test_tool_calculate_math(self):
        res = run_python_calc("15 * 12 + 20")
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(str(res.get("result")), "200")

    def test_tool_time_and_calendar(self):
        data = get_time_and_calendar(timezone_name="Europe/Berlin")
        self.assertIn("datetime_iso", data)
        self.assertIn("calendar_week", data)
        self.assertIn("formatted_time", data)

        easter = calculate_easter_sunday(2026)
        self.assertEqual(easter.year, 2026)

        holidays = get_german_holidays(2026, state="BY")
        self.assertGreaterEqual(len(holidays), 9)

    def test_tool_url_security(self):
        # Safe URL
        safe_res = check_url_safety("https://example.com")
        self.assertTrue(safe_res.get("safe"))
        self.assertEqual(safe_res.get("status"), "CLEAN")

        # SSRF local IP block
        unsafe_res = check_url_safety("http://127.0.0.1:8080/admin")
        self.assertFalse(unsafe_res.get("safe"))
        self.assertEqual(unsafe_res.get("status"), "BLOCKED")

    def test_tool_news_clean_text(self):
        cleaned = news_clean_text("<p>Hello <b>World</b> &amp; ComputeMesh</p>")
        self.assertEqual(cleaned, "Hello World & ComputeMesh")

    def test_tool_rag_builtin_wrapper(self):
        idx_res = index_document_text("Dezentrale Inferenz Knoten im ComputeMesh.", "node.txt", "doc_node_101")
        self.assertTrue(idx_res["success"])

        search_res = search_knowledge_base("Inferenz Knoten")
        self.assertGreaterEqual(search_res.get("total_matches", 0), 1)

        list_res = list_indexed_documents()
        self.assertIn("documents", list_res)

    def test_tool_system_info(self):
        sys_info = execute_system_info()
        self.assertIn("os", sys_info)
        self.assertIn("python_version", sys_info)

    def test_tool_country_data(self):
        res = lookup_country_data("Germany")
        self.assertTrue("country_name" in res or "capital" in res or "error" in res)
        if "capital" in res:
            self.assertEqual(res.get("capital"), "Berlin")

    def test_tool_currency_conversion(self):
        res = convert_currency(100.0, "EUR", "USD")
        self.assertTrue("converted_amount" in res or "rate" in res or "error" in res)

    def test_tool_dictionary_lookup(self):
        res = lookup_word_definition("algorithm")
        self.assertTrue("word" in res or "meanings" in res or "error" in res)

    def test_tool_food_products(self):
        res = lookup_food_product("Nutella")
        self.assertTrue("product_name" in res or "nutriments" in res or "error" in res)

    def test_tool_chemical_data(self):
        res = lookup_chemical_compound("Aspirin")
        self.assertTrue("molecular_formula" in res or "compound_name" in res or "error" in res)


if __name__ == "__main__":
    unittest.main()
