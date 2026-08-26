from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import patch

from services.gateway.inference_backend import (
    DisabledInferenceBackend,
    InferenceBackendError,
    OllamaHTTPBackend,
    OpenAICompatibleHTTPBackend,
    SyntheticInferenceBackend,
    build_inference_backend_from_env,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit: int) -> bytes:
        return self._raw


class InferenceBackendTests(unittest.TestCase):
    def test_default_backend_fails_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            backend = build_inference_backend_from_env()
        self.assertIsInstance(backend, DisabledInferenceBackend)
        with self.assertRaises(InferenceBackendError):
            backend.complete(model_id="model", messages=[])

    def test_synthetic_requires_explicit_double_opt_in(self) -> None:
        with patch.dict(os.environ, {"COMPUTEMESH_INFERENCE_BACKEND": "synthetic"}, clear=True):
            with self.assertRaises(InferenceBackendError):
                build_inference_backend_from_env()

        env = {
            "COMPUTEMESH_INFERENCE_BACKEND": "synthetic",
            "COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            backend = build_inference_backend_from_env()
        self.assertIsInstance(backend, SyntheticInferenceBackend)

    def test_openai_compatible_backend_uses_runtime_usage(self) -> None:
        backend = OpenAICompatibleHTTPBackend(base_url="http://127.0.0.1:8080", model_override="runtime-model")
        response = _FakeResponse(
            {
                "choices": [{"message": {"content": "real runtime output"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
        )
        def fake_urlopen(req, timeout):
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["model"], "runtime-model")
            return response

        with patch("services.gateway.inference_backend.request.urlopen", side_effect=fake_urlopen):
            result = backend.complete(
                model_id="test-model",
                messages=[{"role": "user", "content": "hello"}],
            )
        self.assertEqual(result.text, "real runtime output")
        self.assertEqual(result.prompt_tokens, 11)
        self.assertEqual(result.completion_tokens, 7)

    def test_invalid_runtime_response_is_rejected(self) -> None:
        backend = OpenAICompatibleHTTPBackend(base_url="http://127.0.0.1:8080")
        with patch(
            "services.gateway.inference_backend.request.urlopen",
            return_value=_FakeResponse({"choices": []}),
        ):
            with self.assertRaises(InferenceBackendError):
                backend.complete(model_id="test-model", messages=[])

    def test_invalid_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OpenAICompatibleHTTPBackend(base_url="file:///tmp/runtime.sock")

    def test_ollama_backend_normalizes_chat_response(self) -> None:
        backend = OllamaHTTPBackend(
            base_url="http://127.0.0.1:11434",
            model_override="qwen2.5:1.5b-instruct",
            num_predict=32,
            num_ctx=256,
            num_thread=2,
            system_prompt="You are the ComputeMesh demo assistant.",
        )
        response = _FakeResponse(
            {
                "message": {"role": "assistant", "content": "real ollama answer"},
                "prompt_eval_count": 13,
                "eval_count": 9,
            }
        )

        def fake_urlopen(req, timeout):
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["model"], "qwen2.5:1.5b-instruct")
            self.assertEqual(body["stream"], False)
            self.assertEqual(body["options"]["num_predict"], 32)
            self.assertEqual(body["options"]["num_ctx"], 256)
            self.assertEqual(body["options"]["num_thread"], 2)
            self.assertEqual(body["messages"][0]["role"], "system")
            self.assertEqual(body["messages"][0]["content"], "You are the ComputeMesh demo assistant.")
            return response

        with patch("services.gateway.inference_backend.request.urlopen", side_effect=fake_urlopen):
            result = backend.complete(
                model_id="public-model-alias",
                messages=[{"role": "user", "content": "hello"}],
            )
        self.assertEqual(result.text, "real ollama answer")
        self.assertEqual(result.prompt_tokens, 13)
        self.assertEqual(result.completion_tokens, 9)

    def test_ollama_backend_can_be_selected_from_env(self) -> None:
        env = {
            "COMPUTEMESH_INFERENCE_BACKEND": "ollama",
            "COMPUTEMESH_INFERENCE_URL": "http://127.0.0.1:11434",
            "COMPUTEMESH_INFERENCE_MODEL": "llama3.2:1b",
            "COMPUTEMESH_INFERENCE_CONTEXT_TOKENS": "256",
            "COMPUTEMESH_INFERENCE_THREADS": "2",
            "COMPUTEMESH_INFERENCE_SYSTEM_PROMPT": "You are concise.",
        }
        with patch.dict(os.environ, env, clear=True):
            backend = build_inference_backend_from_env()
        self.assertIsInstance(backend, OllamaHTTPBackend)


if __name__ == "__main__":
    unittest.main()
