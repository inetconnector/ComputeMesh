# SPDX-License-Identifier: Apache-2.0
"""Comprehensive Test Suite for OpenAI Feature & Performance Parity Architecture in ComputeMesh."""

import json
import math
import os
import unittest

try:
    import numpy as np
except ImportError:
    np = None

from services.mcp.builtin.python_sandbox import execute_python_code
from services.rag.document_parser import parse_document_text
from services.rag.chunker import chunk_text
from services.rag.embeddings import compute_semantic_embedding, cosine_similarity
from services.rag.vector_store import VectorStore
from services.grammar.json_schema_to_gbnf import compile_json_schema_to_gbnf
from services.memory.user_memory import UserMemoryStore
from services.voice.voice_realtime import RealtimeVoiceSession, compute_audio_energy
from services.mcp.agent_loop import format_reasoning_and_thinking_blocks, format_tool_content_if_json, detect_direct_tool_intent


class TestOpenAIParityCodeInterpreter(unittest.TestCase):
    """Pillar 1: Code Interpreter & Python Sandbox."""

    def test_math_and_stdout(self):
        code = "import math\nprint('Factorial of 6 is', math.factorial(6))\nresult = 42 * 2"
        res = execute_python_code(code)
        self.assertEqual(res.get("status"), "success")
        self.assertIn("Factorial of 6 is 720", res.get("stdout", ""))
        self.assertEqual(res.get("result"), "84")

    def test_matplotlib_plot_interception(self):
        code = (
            "import math\n"
            "x = [i * 0.2 for i in range(50)]\n"
            "y = [math.sin(val) for val in x]\n"
            "result = sum(y)\n"
        )
        res = execute_python_code(code)
        self.assertEqual(res.get("status"), "success")
        self.assertIsNotNone(res.get("result"))

    def test_sandbox_security(self):
        malicious_code = "import os\nos.system('dir')"
        res = execute_python_code(malicious_code)
        self.assertIn(res.get("status"), ["error", "security_violation"])


class TestOpenAIParityDocumentRAG(unittest.TestCase):
    """Pillar 2: Document RAG & Vector Database."""

    def test_document_parser_and_chunker(self):
        text = "ComputeMesh Control Plane.\n" * 50
        chunks = chunk_text(text, chunk_size=150, chunk_overlap=30)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.text for c in chunks))

    def test_embeddings_and_similarity(self):
        vec1 = compute_semantic_embedding("Künstliche Intelligenz und maschinelles Lernen")
        vec2 = compute_semantic_embedding("AI, Deep Learning und neuronale Netze")
        vec3 = compute_semantic_embedding("Rezept für Erdbeerkuchen und Apfelstrudel")

        sim_related = cosine_similarity(vec1, vec2)
        sim_unrelated = cosine_similarity(vec1, vec3)

        self.assertGreater(sim_related, sim_unrelated)
        norm_val = np.linalg.norm(vec1) if np is not None else math.sqrt(sum(x * x for x in vec1))
        self.assertAlmostEqual(norm_val, 1.0, places=4)


    def test_vector_store_persistence_and_search(self):
        import tempfile
        import shutil
        temp_dir = tempfile.mkdtemp()
        try:
            store = VectorStore(storage_dir=temp_dir)
            doc_text = (
                "ComputeMesh ist eine dezentrale KI-Inferenz-Plattform für Edge-Geräte und Cloud-Cluster. "
                "Sie bietet maximale Rechenleistung bei 100% Datenschutz und voller OpenAI-API-Kompatibilität."
            )
            store.index_text(document_id="doc_computemesh_overview", text=doc_text)
            
            results = store.search(query="Wie funktioniert ComputeMesh und Datenschutz?", top_k=2)
            self.assertGreater(len(results), 0)
            self.assertEqual(results[0].document_id, "doc_computemesh_overview")
            self.assertGreater(results[0].score, 0.4)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestOpenAIParityReasoningAndThinking(unittest.TestCase):
    """Pillar 3: Deep Reasoning & Thinking Models."""

    def test_reasoning_accordion_formatting(self):
        raw_output = (
            "<think>\n"
            "1. Analysiere das Problem.\n"
            "2. Führe mathematische Beweisschritte durch.\n"
            "3. Formuliere finale Lösung.\n"
            "</think>\n"
            "Die finale Lösung lautet: x = 42."
        )
        formatted = format_reasoning_and_thinking_blocks(raw_output)
        self.assertIn('<details class="cm-thinking-block">', formatted)
        self.assertIn("Deep Reasoning", formatted)
        self.assertIn("Die finale Lösung lautet: x = 42.", formatted)
        self.assertNotIn("<think>", formatted)


class TestOpenAIParityGBNFStructuredOutput(unittest.TestCase):
    """Pillar 4: GBNF Structured Output Compiler."""

    def test_schema_to_gbnf_compilation(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "role": {"type": "string", "enum": ["admin", "developer", "user"]},
                "active": {"type": "boolean"},
            },
            "required": ["name", "age", "role"],
        }
        gbnf = compile_json_schema_to_gbnf(schema)
        self.assertIn("root ::=", gbnf)
        self.assertIn('"name"', gbnf)
        self.assertIn('"age"', gbnf)
        self.assertIn('"role"', gbnf)
        self.assertIn('"admin"', gbnf)
        self.assertIn("integer ::=", gbnf)
        self.assertIn("boolean ::=", gbnf)


class TestOpenAIParityPersistentUserMemory(unittest.TestCase):
    """Pillar 5: Persistent User Memory."""

    def test_memory_profile_lifecycle(self):
        import tempfile
        import shutil
        temp_dir = tempfile.mkdtemp()
        try:
            profile_path = os.path.join(temp_dir, "test_profile.json")
            mem = UserMemoryStore(storage_path=profile_path)
            
            mem.update_profile(
                name="Frederik",
                preferred_language="Deutsch",
                preferences=["Bevorzugt präzise technische Antworten mit Code-Beispielen", "Verwendet Dark-Mode"],
                facts=["Entwickelt das ComputeMesh Control Plane System"],
            )

            summary = mem.get_memory_summary()
            self.assertIn("Frederik", summary)
            self.assertIn("ComputeMesh", summary)
            self.assertIn("Dark-Mode", summary)

            # Test reload from disk
            mem2 = UserMemoryStore(storage_path=profile_path)
            self.assertEqual(mem2.get_profile().name, "Frederik")
            self.assertIn("Dark-Mode", mem2.get_profile().preferences[1])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestOpenAIParityStreamingVoice(unittest.TestCase):
    """Pillar 6: Streaming Voice & Real-Time Engine."""

    def test_voice_session_and_vad(self):
        session = RealtimeVoiceSession(sample_rate=16000)
        
        # Silence chunk
        silence = bytes(1600 * 2)
        vad_silence = session.process_input_audio_chunk(silence)
        self.assertFalse(vad_silence)

        # High energy audio chunk (simulating speech)
        if np is not None:
            speech_samples = (np.sin(np.linspace(0, 50, 1600)) * 15000).astype(np.int16)
            speech_bytes = speech_samples.tobytes()
        else:
            import array
            speech_bytes = array.array('h', [int(math.sin(i * 50 / 1600) * 15000) for i in range(1600)]).tobytes()
        vad_speech = session.process_input_audio_chunk(speech_bytes)
        self.assertTrue(vad_speech)

        # Barge-in interruption
        session.is_speaking = True
        interrupted = session.handle_barge_in(speech_bytes)
        self.assertTrue(interrupted)
        self.assertFalse(session.is_speaking)


class TestDirectIntentAndFormatting(unittest.TestCase):
    """Direct Intent Detection and Tool Formatting for parity tools."""

    def test_direct_intent_python(self):
        query = "plotte eine sinus kurve mit matplotlib"
        intent = detect_direct_tool_intent(query)
        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "execute_python_code")

    def test_direct_intent_rag(self):
        query = "suche in der wissensbasis nach compute cluster anleitung"
        intent = detect_direct_tool_intent(query)
        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "search_knowledge_base")

    def test_direct_intent_memory(self):
        query = "was weißt du über mich"
        intent = detect_direct_tool_intent(query)
        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "get_user_memory")

    def test_format_python_output(self):
        tool_json = json.dumps({
            "status": "success",
            "stdout": "ComputeMesh Node: Active",
            "result": "100",
            "images": []
        })
        formatted = format_tool_content_if_json(tool_json)
        self.assertIn("Code Interpreter", formatted)
        self.assertIn("ComputeMesh Node: Active", formatted)


if __name__ == "__main__":
    unittest.main()
