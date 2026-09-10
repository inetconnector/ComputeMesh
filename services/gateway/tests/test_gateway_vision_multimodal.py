"""Unit and integration tests for ComputeMesh Multimodal Vision API."""
from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PIL import Image
from services.billing.accounting import AccountingStore
from services.billing.ledger import Ledger
from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import SyntheticInferenceBackend
from services.gateway.server import GatewayHandler
from services.gateway.teaser import TeaserQuotaManager


class TestGatewayVisionMultimodal(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._orig_ledger = GatewayHandler.ledger
        cls._orig_account_store = GatewayHandler.account_store
        cls._orig_teaser = GatewayHandler.teaser_manager
        cls._orig_inference_engine = GatewayHandler.inference_engine

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.account_store = AccountingStore(Path(cls.temp_dir.name) / "accounting.sqlite")
        db_path = Path(cls.temp_dir.name) / "test_vision_ledger.sqlite3"
        cls.ledger = Ledger(str(db_path))
        cls.ledger.deposit_customer_credits(
            customer_account_id="cust_vision_test",
            amount_micro_units=500_000_000,
            payment_reference="stripe_pi_vision_001",
        )
        cls.teaser = TeaserQuotaManager(max_requests=20, max_tokens=8192)
        cls.backend = SyntheticInferenceBackend()
        cls.engine = InferenceEngine(
            ledger=cls.ledger,
            metrics=GatewayHandler.metrics,
            teaser_manager=cls.teaser,
            backend=cls.backend,
        )

        GatewayHandler.ledger = cls.ledger
        GatewayHandler.account_store = cls.account_store
        GatewayHandler.teaser_manager = cls.teaser
        GatewayHandler.inference_engine = cls.engine
        GatewayHandler.sync_subsystems()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2.0)
        GatewayHandler.ledger = cls._orig_ledger
        GatewayHandler.account_store = cls._orig_account_store
        GatewayHandler.teaser_manager = cls._orig_teaser
        GatewayHandler.inference_engine = cls._orig_inference_engine
        GatewayHandler.sync_subsystems()
        cls.temp_dir.cleanup()

    def _create_test_image_b64(self, width: int = 400, height: int = 300, fmt: str = "JPEG") -> str:
        img = Image.new("RGB", (width, height), (100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def test_openai_multimodal_chat_completion(self) -> None:
        b64 = self._create_test_image_b64(800, 600)
        data_uri = f"data:image/jpeg;base64,{b64}"

        payload = {
            "model": "qwen2.5-vl:7b",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Bitte analysiere dieses Bild professionell."},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            "stream": False,
        }

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cust_vision_test",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data["object"], "chat.completion")
        self.assertEqual(data["model"], "qwen/qwen2.5-vl-7b-instruct")
        content = data["choices"][0]["message"]["content"]
        self.assertIn("Vision Analysis", content)
        self.assertIn("Scene Overview", content)
        self.assertGreater(data["usage"]["prompt_tokens"], 50)
        self.assertGreater(data["usage"]["completion_tokens"], 10)

    def test_openai_multimodal_streaming(self) -> None:
        b64 = self._create_test_image_b64(600, 400)
        payload = {
            "model": "llama3.2-vision",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Vision stream test."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            "stream": True,
        }

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cust_vision_test",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10.0) as resp:
            self.assertEqual(resp.status, 200)
            raw = resp.read().decode("utf-8")

        self.assertIn("data: {", raw)
        self.assertIn("[DONE]", raw)

    def test_ollama_multimodal_chat(self) -> None:
        b64 = self._create_test_image_b64(500, 500)
        payload = {
            "model": "llava:7b",
            "messages": [
                {
                    "role": "user",
                    "content": "Beschreibe die Grafik",
                    "images": [b64],
                }
            ],
            "stream": False,
        }

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cust_vision_test",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data["model"], "llava/llava-1.6-7b")
        self.assertTrue(data["done"])
        self.assertIn("Vision Analysis", data["message"]["content"])
        self.assertGreater(data["prompt_eval_count"], 50)

    def test_ollama_multimodal_generate(self) -> None:
        b64 = self._create_test_image_b64(400, 400)
        payload = {
            "model": "qwen2.5-vl:7b",
            "prompt": "Was ist auf dem Foto zu sehen?",
            "images": [b64],
            "stream": False,
        }

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cust_vision_test",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(data["model"], "qwen/qwen2.5-vl-7b-instruct")
        self.assertTrue(data["done"])
        self.assertIn("response", data)
        self.assertIn("Vision Analysis", data["response"])

    def test_ollama_tags_and_show_for_vision(self) -> None:
        # 1. Tags listing
        req_tags = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/tags")
        with urllib.request.urlopen(req_tags, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            tags_data = json.loads(resp.read().decode("utf-8"))

        model_names = [m["name"] for m in tags_data["models"]]
        self.assertIn("qwen/qwen2.5-vl-7b-instruct", model_names)
        self.assertIn("llava/llava-1.6-7b", model_names)

        # 2. Show vision model
        req_show = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/show",
            data=json.dumps({"name": "qwen2.5-vl:7b"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_show, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            show_data = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(show_data["details"]["family"], "qwen2_vl")
        self.assertIn("clip", show_data["details"]["families"])


if __name__ == "__main__":
    unittest.main()
