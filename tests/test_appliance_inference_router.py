"""Regression tests for strict local model selection."""
from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.appliance_dashboard.inference_router import InferenceRouter, _ollama_message


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _Handler:
    def __init__(self) -> None:
        self.responses = []
        self.tokens_served = 0
        self.earnings_cm = 0

    def _send_json(self, payload, status=HTTPStatus.OK):
        self.responses.append((status, payload))

    def _current_node_id(self):
        return "test-node"


class TestStrictLocalModelSelection(unittest.TestCase):
    def test_multimodal_message_uses_ollama_image_field(self):
        result = _ollama_message(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Was steht da"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}},
                ],
            }
        )

        self.assertEqual(result["content"], "Was steht da")
        self.assertEqual(result["images"], ["QUJD"])
        self.assertNotIn("data:image", result["content"])

    def test_image_input_rejects_text_only_model_without_echoing_base64(self):
        handler = _Handler()
        image_payload = "data:image/jpeg;base64,SECRET_IMAGE_BYTES"

        with patch(
            "services.appliance_dashboard.inference_router.urllib.request.urlopen",
            return_value=_Response(
                {"models": [{"name": "qwen2.5-coder:14b"}, {"name": "gemma3:4b"}]}
            ),
        ):
            handled = InferenceRouter.handle_post(
                handler,
                "/webui/chat/completions",
                json.dumps(
                    {
                        "model": "qwen2.5-coder:14b",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Was steht da"},
                                    {"type": "image_url", "image_url": {"url": image_payload}},
                                ],
                            }
                        ],
                    }
                ).encode("utf-8"),
            )

        self.assertTrue(handled)
        status, payload = handler.responses[0]
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(payload["error"]["code"], "vision_model_required")
        self.assertEqual(payload["error"]["available_vision_models"], ["gemma3:4b"])
        self.assertNotIn("SECRET_IMAGE_BYTES", json.dumps(payload))

    def test_explicit_unknown_model_is_rejected_instead_of_replaced(self):
        handler = _Handler()

        with patch(
            "services.appliance_dashboard.inference_router.urllib.request.urlopen",
            return_value=_Response({"models": [{"name": "gemma4:26b"}]}),
        ):
            handled = InferenceRouter.handle_post(
                handler,
                "/webui/chat/completions",
                json.dumps(
                    {
                        "model": "qwen2.5:7b",
                        "messages": [{"role": "user", "content": "Hallo"}],
                    }
                ).encode("utf-8"),
            )

        self.assertTrue(handled)
        self.assertEqual(len(handler.responses), 1)
        status, payload = handler.responses[0]
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(payload["error"]["code"], "model_not_available")
        self.assertEqual(payload["error"]["available_models"], ["gemma4:26b"])

    def test_active_managed_gguf_uses_llama_server_endpoint(self):
        handler = _Handler()
        requested_urls = []

        def open_runtime(request, timeout=0):
            requested_urls.append(request.full_url)
            return _Response({
                "choices": [{"message": {"role": "assistant", "content": "Echte Runtime-Antwort"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
            })

        managed = {
            "engine": {
                "ready": True,
                "endpoint": "http://127.0.0.1:8081",
                "model_id": "org/real-model-q4",
            },
            "models": [],
        }
        with patch("services.appliance_dashboard.inference_router._managed_runtime_status", return_value=managed), patch(
            "services.appliance_dashboard.inference_router.urllib.request.urlopen",
            side_effect=open_runtime,
        ), patch("tools.appliance.token_metering.record_tokens") as meter:
            meter.return_value.total_tokens_served = 12
            meter.return_value.earnings_cm = 0
            handled = InferenceRouter.handle_post(
                handler,
                "/v1/chat/completions",
                json.dumps({
                    "model": "org/real-model-q4",
                    "messages": [{"role": "user", "content": "Hallo"}],
                    "stream": False,
                }).encode("utf-8"),
            )

        self.assertTrue(handled)
        self.assertEqual(requested_urls, ["http://127.0.0.1:8081/v1/chat/completions"])
        status, payload = handler.responses[-1]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["choices"][0]["message"]["content"], "Echte Runtime-Antwort")
        self.assertEqual(payload["usage"]["total_tokens"], 12)
        meter.assert_called_once_with(prompt_tokens=7, completion_tokens=5)


if __name__ == "__main__":
    unittest.main()
