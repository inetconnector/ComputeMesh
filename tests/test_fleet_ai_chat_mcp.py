"""Unit and Integration Tests for ComputeMesh Fleet AI-Chat, llama.cpp WebUI, and MCP Live-Tools."""
from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import services.gateway.server as gateway_server_module
from services.gateway.server import GatewayHandler, create_gateway_server
from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import SyntheticInferenceBackend


class TestFleetAIChatAndMCP(unittest.TestCase):
    """End-to-End test suite ensuring AI-Chat and MCP tools never break in production."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.orig_engine = GatewayHandler.inference_engine
        GatewayHandler.inference_engine = InferenceEngine(
            ledger=GatewayHandler.ledger,
            metrics=GatewayHandler.metrics,
            teaser_manager=GatewayHandler.teaser_manager,
            backend=SyntheticInferenceBackend(),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        GatewayHandler.inference_engine = cls.orig_engine

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.server, self.port = create_gateway_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.15)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp_dir.cleanup()

    def _get(self, path: str, headers: dict = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        req_headers = headers or {}
        conn.request("GET", path, headers=req_headers)
        res = conn.getresponse()
        raw = res.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        conn.close()
        return res.status, payload

    def _post(self, path: str, body: dict, headers: dict = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = json.dumps(body).encode("utf-8")
        req_headers = {"Content-Type": "application/json", "Content-Length": str(len(data))}
        if headers:
            req_headers.update(headers)
        conn.request("POST", path, body=data, headers=req_headers)
        res = conn.getresponse()
        raw = res.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        conn.close()
        return res.status, payload

    def test_webui_props_handshake(self):
        """WebUI frontend requires /props and /webui/props to initialize."""
        for path in ("/props", "/webui/props", "/api/props", "/v1/props"):
            status, data = self._get(path)
            self.assertEqual(status, 200, f"Failed GET {path}")
            self.assertIn("default_generation_settings", data)
            self.assertIn("webui_settings", data)
            self.assertEqual(data["default_generation_settings"]["n_ctx"], 32768)

    def test_webui_slots_handshake(self):
        """WebUI frontend requires /slots and /webui/slots."""
        for path in ("/slots", "/webui/slots"):
            status, data = self._get(path)
            self.assertEqual(status, 200, f"Failed GET {path}")
            self.assertIsInstance(data, list)
            self.assertGreaterEqual(len(data), 1)
            self.assertIn("model", data[0])

    def test_mcp_tools_discovery_endpoint(self):
        """MCP tools must be registered and exposed for OpenAI function calling."""
        for path in ("/v1/mcp/tools", "/api/v1/mcp/tools", "/mcp/tools"):
            status, data = self._get(path)
            self.assertEqual(status, 200, f"Failed GET {path}")
            self.assertEqual(data.get("object"), "list")
            tools = data.get("data", [])
            self.assertGreaterEqual(len(tools), 15, f"Expected at least 15 MCP tools, found {len(tools)}")
            tool_names = [t.get("function", {}).get("name") for t in tools if "function" in t]
            self.assertIn("get_current_weather", tool_names)
            self.assertIn("search_web", tool_names)
            self.assertIn("get_market_quote", tool_names)
            self.assertIn("get_wikipedia_summary", tool_names)
            self.assertIn("get_distance_route", tool_names)
            self.assertIn("lookup_train_schedule", tool_names)

    def test_chat_completions_with_mcp_weather(self):
        """Executing a live weather query in AI-Chat dispatches get_live_weather MCP tool."""
        status, data = self._post(
            "/v1/chat/completions",
            body={
                "model": "qwen2.5:7b",
                "messages": [{"role": "user", "content": "Wie ist das Wetter in Berlin?"}],
                "stream": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("choices", data)
        content = data["choices"][0]["message"]["content"]
        self.assertTrue(
            "Berlin" in content or "Wetter" in content or "Live-Daten" in content or "Temperatur" in content,
            f"Expected weather data in answer, got: {content}"
        )

    def test_chat_completions_with_mcp_stock_price(self):
        """Executing a stock/crypto query dispatches lookup_stock_crypto_price MCP tool."""
        status, data = self._post(
            "/webui/chat/completions",
            body={
                "messages": [{"role": "user", "content": "Was ist der aktuelle Kurs von BTC?"}],
                "stream": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("choices", data)
        content = data["choices"][0]["message"]["content"]
        self.assertTrue(
            "BTC" in content or "Bitcoin" in content or "$" in content or "Live-Kurs" in content or "USD" in content,
            f"Expected financial live data in answer, got: {content}"
        )

    def test_chat_completions_with_fleet_owner_key(self):
        """Fleet Owner Key authentication allows unlimited priority chat."""
        headers = {"X-Owner-Key": "inet-89d428edbdf525ce956f34d622bba1faf8f38701"}
        status, data = self._post(
            "/v1/chat/completions",
            body={
                "model": "meta-llama/llama-3.3-70b-instruct",
                "messages": [{"role": "user", "content": "Flotten-Testnachricht"}],
                "stream": False,
            },
            headers=headers,
        )
        self.assertEqual(status, 200)
        self.assertIn("choices", data)

    def test_ollama_chat_api(self):
        """Ollama compatibility route /api/chat works properly."""
        status, data = self._post(
            "/api/chat",
            body={
                "model": "qwen2.5:7b",
                "messages": [{"role": "user", "content": "Hallo Ollama Mesh!"}],
                "stream": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("message", data)
        self.assertEqual(data["message"]["role"], "assistant")

    def test_node_tunnel_chat_and_mcp(self):
        """Cellular node tunnel route /node/<node_id>/v1/chat/completions works transparently."""
        status, data = self._post(
            "/node/cm-inference-node-01/v1/chat/completions",
            body={
                "model": "qwen2.5:7b",
                "messages": [{"role": "user", "content": "Wie ist das Wetter in Berlin?"}],
                "stream": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("choices", data)
        content = data["choices"][0]["message"]["content"]
        self.assertTrue(
            "Berlin" in content or "Wetter" in content or "Live-Daten" in content or "Temperatur" in content,
            f"Expected weather data in tunneled node answer, got: {content}"
        )

        # Also verify GET /node/<node_id>/props
        status, props = self._get("/node/cm-inference-node-01/props")
        self.assertEqual(status, 200)
        self.assertIn("default_generation_settings", props)


if __name__ == "__main__":
    unittest.main()

