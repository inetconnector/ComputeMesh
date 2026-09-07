"""Unit and Integration Tests for llama.cpp WebUI and OpenAI endpoints in ComputeMesh Gateway."""
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


class TestLlamaCppWebUIGateway(unittest.TestCase):
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

    def _get(self, path: str):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        res = conn.getresponse()
        raw = res.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        conn.close()
        return res.status, payload

    def _post(self, path: str, body: dict):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(data))}
        conn.request("POST", path, body=data, headers=headers)
        res = conn.getresponse()
        raw = res.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        conn.close()
        return res.status, payload

    def test_get_props(self):
        status, data = self._get("/props")
        self.assertEqual(status, 200)
        self.assertIn("default_generation_settings", data)
        self.assertIn("total_slots", data)
        self.assertIn("chat_template", data)
        self.assertIn("webui_settings", data)

    def test_get_webui_props(self):
        status, data = self._get("/webui/props")
        self.assertEqual(status, 200)
        self.assertIn("default_generation_settings", data)
        self.assertEqual(data["default_generation_settings"]["n_ctx"], 32768)

    def test_get_slots(self):
        status, data = self._get("/slots")
        self.assertEqual(status, 200)
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]["id"], 0)

    def test_get_webui_slots(self):
        status, data = self._get("/webui/slots")
        self.assertEqual(status, 200)
        self.assertIsInstance(data, list)

    def test_get_health(self):
        status, data = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("status"), "ok")

    def test_get_models(self):
        status, data = self._get("/models")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("object"), "list")
        self.assertIn("data", data)

    def test_get_webui_models(self):
        status, data = self._get("/webui/models")
        self.assertEqual(status, 200)
        self.assertEqual(data.get("object"), "list")

    def test_post_completion_prompt(self):
        status, data = self._post("/completion", body={"prompt": "Hallo!", "stream": False})
        self.assertEqual(status, 200)
        self.assertIn("choices", data)

    def test_post_webui_chat_completions(self):
        status, data = self._post(
            "/webui/chat/completions",
            body={"messages": [{"role": "user", "content": "Hallo ComputeMesh!"}], "stream": False},
        )
        self.assertEqual(status, 200)
        self.assertIn("choices", data)

    def test_post_webui_chat_mcp_weather(self):
        status, data = self._post(
            "/webui/chat/completions",
            body={
                "messages": [{"role": "user", "content": "wie ist das wetter in veitshöchheim"}],
                "stream": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("choices", data)
        content = data["choices"][0]["message"]["content"]
        self.assertTrue(
            "Live-Daten" in content or "Veitshöchheim" in content or "Wetter" in content,
            f"Expected live tool synthesized answer, got: {content}",
        )

    def test_post_tokenize_detokenize(self):
        status, data = self._post("/tokenize", body={"content": "Hello"})
        self.assertEqual(status, 200)
        self.assertIn("tokens", data)

        status, detok = self._post("/detokenize", body={"tokens": data["tokens"]})
        self.assertEqual(status, 200)
        self.assertEqual(detok.get("content"), "Hello")


if __name__ == "__main__":
    unittest.main()
