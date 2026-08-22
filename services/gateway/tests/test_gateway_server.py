"""Unit tests for ComputeMesh OpenAI-Compatible Streaming API Gateway."""
from http.server import ThreadingHTTPServer
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from services.gateway.server import GatewayHandler


class TestGatewayServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 18000), GatewayHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_healthz(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:18000/healthz") as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")

    def test_unauthenticated_request_rejected(self) -> None:
        req = urllib.request.Request("http://127.0.0.1:18000/v1/models")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_list_models_openai_format(self) -> None:
        req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/models",
            headers={"Authorization": "Bearer cm_live_test_key_001"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["object"], "list")
            model_ids = [m["id"] for m in data["data"]]
            self.assertIn("qwen/qwen2.5-7b-instruct", model_ids)
            self.assertIn("llama/llama-3.1-70b-instruct", model_ids)

    def test_chat_completions_non_streaming(self) -> None:
        payload = {
            "model": "qwen/qwen2.5-7b-instruct",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Explain decentralized AI in one sentence."},
            ],
            "stream": False,
        }
        req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_live_test_key_002",
            },
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["object"], "chat.completion")
            self.assertTrue(data["id"].startswith("chatcmpl-"))
            self.assertEqual(len(data["choices"]), 1)
            self.assertEqual(data["choices"][0]["finish_reason"], "stop")
            self.assertIn("usage", data)
            self.assertGreater(data["usage"]["total_tokens"], 0)

    def test_chat_completions_streaming_sse(self) -> None:
        payload = {
            "model": "qwen/qwen2.5-7b-instruct",
            "messages": [
                {"role": "user", "content": "Hello streaming world!"},
            ],
            "stream": True,
        }
        req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_live_test_key_003",
            },
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            raw_sse = resp.read().decode("utf-8")
            self.assertIn("data: ", raw_sse)
            self.assertIn("[DONE]", raw_sse)

    def test_balance_and_metering(self) -> None:
        key = "cm_live_test_key_004"
        bal_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/billing/balance",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(bal_req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            init_bal = data["balance_usd"]
            self.assertGreater(init_bal, 0.0)

    def test_billing_checkout_and_webhook(self) -> None:
        key = "cm_live_test_key_stripe"
        # 1. Create Checkout Session
        checkout_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/billing/checkout",
            data=json.dumps({"amount_usd": 50.00}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(checkout_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["session_id"].startswith("cs_test_"))
            self.assertIn("checkout.stripe.com", data["checkout_url"])
            session_id = data["session_id"]
            cust_account_id = data["customer_account_id"]

        # 2. Ingest Webhook Event
        webhook_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/billing/webhook",
            data=json.dumps({
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": session_id,
                        "amount_total": 5000,
                        "client_reference_id": cust_account_id,
                    }
                },
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(webhook_req) as resp:
            self.assertEqual(resp.status, 200)
            wh_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(wh_data["status"], "credited")
            self.assertEqual(wh_data["amount_usd"], 50.00)


if __name__ == "__main__":
    unittest.main()

