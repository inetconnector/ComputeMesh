from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from apps.client.confidential_openai import ConfidentialOpenAIError
from apps.client.openai_proxy import create_proxy_server


class FakeBridge:
    def complete(self, *, authorization: str, body: dict) -> dict:
        if authorization != "Bearer cm_test_key_123":
            raise ConfidentialOpenAIError("Unauthorized", status=401, error_type="authentication_error")
        return {
            "id": "chatcmpl-test-123",
            "object": "chat.completion",
            "created": 1700000000,
            "model": body.get("model", "qwen/qwen2.5-7b-instruct"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Decrypted response from protected worker.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
        }

    def stream(self, *, authorization: str, body: dict):
        if authorization != "Bearer cm_test_key_123":
            raise ConfidentialOpenAIError("Unauthorized", status=401, error_type="authentication_error")
        chunks = [
            b"data: {\"id\":\"chatcmpl-stream-1\",\"object\":\"chat.completion.chunk\",\"choices\":[{\"index\":0,\"delta\":{\"role\":\"assistant\",\"content\":\"Hello\"},\"finish_reason\":null}]}\n\n",
            b"data: {\"id\":\"chatcmpl-stream-1\",\"object\":\"chat.completion.chunk\",\"choices\":[{\"index\":0,\"delta\":{\"content\":\" world\"},\"finish_reason\":null}]}\n\n",
            b"data: {\"id\":\"chatcmpl-stream-1\",\"object\":\"chat.completion.chunk\",\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
            b"data: [DONE]\n\n",
        ]
        class SimpleStream:
            def __iter__(self):
                return iter(chunks)
            def close(self):
                pass
        return SimpleStream()


class FakeTransport:
    def get_models(self, *, authorization: str) -> tuple[int, bytes, str]:
        if authorization != "Bearer cm_test_key_123":
            raise ConfidentialOpenAIError("Unauthorized", status=401, error_type="authentication_error")
        data = {
            "object": "list",
            "data": [
                {"id": "qwen/qwen2.5-7b-instruct", "object": "model", "owned_by": "computemesh"}
            ]
        }
        return 200, json.dumps(data).encode("utf-8"), "application/json"


class TestOpenAIProxy(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = FakeBridge()
        self.transport = FakeTransport()
        self.server, self.port = create_proxy_server(
            host="127.0.0.1",
            port=0,
            bridge=self.bridge,
            transport=self.transport,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def test_healthz_endpoint(self) -> None:
        req = urllib.request.Request(f"{self.base_url}/healthz")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["service"], "computemesh-local-openai")

    def test_non_streaming_chat_completion(self) -> None:
        payload = {
            "model": "qwen/qwen2.5-7b-instruct",
            "messages": [{"role": "user", "content": "Hello!"}],
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_test_key_123",
            },
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["object"], "chat.completion")
            self.assertEqual(
                data["choices"][0]["message"]["content"],
                "Decrypted response from protected worker.",
            )
            self.assertEqual(data["usage"]["total_tokens"], 20)

    def test_streaming_chat_completion(self) -> None:
        payload = {
            "model": "qwen/qwen2.5-7b-instruct",
            "messages": [{"role": "user", "content": "Stream hello"}],
            "stream": True,
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_test_key_123",
            },
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.headers.get("Content-Type", ""))
            raw = resp.read().decode("utf-8")
            self.assertIn("data: [DONE]", raw)
            self.assertIn("Hello", raw)
            self.assertIn(" world", raw)

    def test_get_models_list(self) -> None:
        req = urllib.request.Request(
            f"{self.base_url}/v1/models",
            headers={"Authorization": "Bearer cm_test_key_123"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["object"], "list")
            self.assertEqual(data["data"][0]["id"], "qwen/qwen2.5-7b-instruct")

    def test_missing_auth_header_fails_with_401(self) -> None:
        payload = {
            "model": "qwen/qwen2.5-7b-instruct",
            "messages": [{"role": "user", "content": "No auth"}],
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)
        data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(data["error"]["type"], "authentication_error")

    def test_invalid_json_body_fails_with_400(self) -> None:
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=b"not valid json",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_test_key_123",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        data = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(data["error"]["type"], "invalid_request_error")

    def test_reject_non_loopback_host(self) -> None:
        with self.assertRaises(ValueError):
            create_proxy_server(
                host="192.168.1.50",
                port=0,
                bridge=self.bridge,
                transport=self.transport,
            )


if __name__ == "__main__":
    unittest.main()
