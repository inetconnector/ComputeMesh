"""Unit tests for ComputeMesh OpenAI-Compatible Streaming API Gateway."""
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from services.billing.ledger import Ledger
from services.billing.accounting import AccountingStore
from services.billing.stripe_connect import SettlementExecutor, StripeConnectService
from services.billing.stripe_integration import StripePaymentService, StripeSessionStore
from services.gateway.server import GatewayHandler


class FakeCheckoutSessionAPI:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **params):
        self.calls.append(params)
        return {
            "id": "cs_test_gateway_001",
            "url": "https://checkout.stripe.com/c/pay/cs_test_gateway_001",
            "customer": "cus_gateway_001",
            "payment_intent": "pi_gateway_001",
            "livemode": False,
        }


class FakeStripeClient:
    def __init__(self) -> None:
        self.checkout_session_api = FakeCheckoutSessionAPI()
        self.checkout = type("Checkout", (), {})()
        self.checkout.Session = self.checkout_session_api
        self.Account = FakeAccountAPI()
        self.AccountLink = FakeAccountLinkAPI()
        self.Transfer = FakeTransferAPI()


class FakeAccountAPI:
    def __init__(self) -> None:
        self.created = []
        self.accounts = {}

    def create(self, **params):
        self.created.append(params)
        account = {
            "id": f"acct_gateway_{len(self.created):03d}",
            "charges_enabled": False,
            "payouts_enabled": False,
            "details_submitted": False,
        }
        self.accounts[account["id"]] = account
        return account

    def retrieve(self, account_id):
        return self.accounts[account_id]


class FakeAccountLinkAPI:
    def create(self, **params):
        return {
            "url": f"https://connect.stripe.com/setup/e/{params['account']}",
            "expires_at": 1893456000,
        }


class FakeTransferAPI:
    def __init__(self) -> None:
        self.created = []

    def create(self, **params):
        self.created.append(params)
        return {"id": f"tr_gateway_{len(self.created):03d}"}


def trusted_json_verifier(raw_payload: bytes, signature_header: str, endpoint_secret: str):
    if signature_header != "t=123,v1=testsig":
        raise ValueError("invalid test signature")
    if endpoint_secret != "whsec_gateway_test":
        raise ValueError("invalid endpoint secret")
    return json.loads(raw_payload.decode("utf-8"))


class TestGatewayServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.fake_stripe = FakeStripeClient()
        GatewayHandler.ledger = Ledger()
        GatewayHandler.account_store = AccountingStore(Path(cls.tempdir.name) / "accounting.sqlite")
        GatewayHandler.stripe_svc = StripePaymentService(
            ledger=GatewayHandler.ledger,
            webhook_secret="whsec_gateway_test",
            stripe_api_key="sk_test_gateway",
            session_store=StripeSessionStore(Path(cls.tempdir.name) / "stripe_sessions.json"),
            webhook_event_store=GatewayHandler.account_store,
            stripe_client=cls.fake_stripe,
            webhook_verifier=trusted_json_verifier,
            require_live_configuration=True,
        )
        GatewayHandler.settlement_executor = SettlementExecutor(
            ledger=GatewayHandler.ledger,
            account_store=GatewayHandler.account_store,
            stripe_connect=StripeConnectService(
                stripe_api_key="sk_test_gateway",
                stripe_client=cls.fake_stripe,
            ),
        )
        GatewayHandler.api_keys = {
            "cm_live_default_test_key": "cust_test_default",
        }
        cls.server = ThreadingHTTPServer(("127.0.0.1", 18000), GatewayHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.tempdir.cleanup()

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

    def test_list_models_ollama_tags_format(self) -> None:
        req = urllib.request.Request(
            "http://127.0.0.1:18000/api/tags",
            headers={"Authorization": "Bearer cm_live_test_key_ollama_tags"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            model_ids = {m["name"] for m in data["models"]}
            self.assertIn("qwen/qwen2.5-7b-instruct", model_ids)
            self.assertIn("llama/llama-3.1-70b-instruct", model_ids)
            first = data["models"][0]
            self.assertEqual(first["details"]["format"], "computemesh-gateway")

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

    def test_ollama_chat_non_streaming(self) -> None:
        payload = {
            "model": "qwen/qwen2.5-7b-instruct",
            "messages": [
                {"role": "user", "content": "Run through the Ollama compatible facade."},
            ],
            "stream": False,
        }
        req = urllib.request.Request(
            "http://127.0.0.1:18000/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_live_test_key_ollama_chat",
            },
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["model"], "qwen/qwen2.5-7b-instruct")
            self.assertTrue(data["done"])
            self.assertEqual(data["message"]["role"], "assistant")
            self.assertIn("ComputeMesh distributed response", data["message"]["content"])
            self.assertGreater(data["eval_count"], 0)

    def test_ollama_generate_non_streaming(self) -> None:
        payload = {
            "model": "qwen/qwen2.5-7b-instruct",
            "prompt": "Run through Ollama generate.",
            "stream": False,
        }
        req = urllib.request.Request(
            "http://127.0.0.1:18000/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_live_test_key_ollama_generate",
            },
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["model"], "qwen/qwen2.5-7b-instruct")
            self.assertTrue(data["done"])
            self.assertIn("ComputeMesh distributed response", data["response"])
            self.assertGreater(data["prompt_eval_count"], 0)

    def test_chat_metering_uses_configured_provider_shares(self) -> None:
        key = "cm_live_test_key_provider_shares"
        before_a = GatewayHandler.ledger.get_balance("provider:node_gateway_share_a")
        before_b = GatewayHandler.ledger.get_balance("provider:node_gateway_share_b")
        old_shares = os.environ.get("COMPUTEMESH_PROVIDER_SHARES")
        os.environ["COMPUTEMESH_PROVIDER_SHARES"] = "node_gateway_share_a:3,node_gateway_share_b:1"
        try:
            payload = {
                "model": "qwen/qwen2.5-7b-instruct",
                "messages": [{"role": "user", "content": "Attribute this metered job."}],
                "stream": False,
            }
            req = urllib.request.Request(
                "http://127.0.0.1:18000/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
        finally:
            if old_shares is None:
                os.environ.pop("COMPUTEMESH_PROVIDER_SHARES", None)
            else:
                os.environ["COMPUTEMESH_PROVIDER_SHARES"] = old_shares

        delta_a = GatewayHandler.ledger.get_balance("provider:node_gateway_share_a") - before_a
        delta_b = GatewayHandler.ledger.get_balance("provider:node_gateway_share_b") - before_b
        self.assertGreater(delta_a, 0)
        self.assertGreater(delta_b, 0)
        self.assertGreater(delta_a, delta_b)

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
                        "currency": "usd",
                        "payment_status": "paid",
                        "client_reference_id": cust_account_id,
                        "customer": "cus_gateway_001",
                        "payment_intent": "pi_gateway_001",
                    }
                },
            }).encode("utf-8"),
            headers={"Content-Type": "application/json", "Stripe-Signature": "t=123,v1=testsig"},
        )
        with urllib.request.urlopen(webhook_req) as resp:
            self.assertEqual(resp.status, 200)
            wh_data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(wh_data["status"], "credited")
            self.assertEqual(wh_data["amount_usd"], 50.00)

    def test_billing_webhook_rejects_missing_signature(self) -> None:
        webhook_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/billing/webhook",
            data=json.dumps({"type": "customer.created"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(webhook_req)
        self.assertEqual(ctx.exception.code, 400)

    def test_prometheus_metrics_endpoint(self) -> None:
        metrics_req = urllib.request.Request("http://127.0.0.1:18000/metrics")
        with urllib.request.urlopen(metrics_req) as resp:
            self.assertEqual(resp.status, 200)
            text = resp.read().decode("utf-8")
            self.assertIn("computemesh_active_gpus", text)
            self.assertIn("computemesh_total_vram_bytes", text)
            self.assertIn("computemesh_requests_total", text)

    def test_provider_registration_status_and_stripe_onboarding(self) -> None:
        provider_key = "cm_provider_node_gateway_provider"
        register_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/providers/register",
            data=json.dumps({
                "display_name": "Gateway Provider",
                "payout_wallet_address": "0x0000000000000000000000000000000000000002",
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {provider_key}",
            },
        )
        with urllib.request.urlopen(register_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["provider_node_id"], "node_gateway_provider")
            self.assertEqual(data["ledger_account_id"], "provider:node_gateway_provider")

        onboarding_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/providers/stripe/onboarding",
            data=json.dumps({
                "email": "gateway-provider@example.test",
                "refresh_url": "https://example.test/refresh",
                "return_url": "https://example.test/return",
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {provider_key}",
            },
        )
        with urllib.request.urlopen(onboarding_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["stripe_connected_account_id"].startswith("acct_gateway_"))
            self.assertIn("connect.stripe.com", data["onboarding_url"])
            stripe_account_id = data["stripe_connected_account_id"]

        self.fake_stripe.Account.accounts[stripe_account_id].update({
            "charges_enabled": True,
            "payouts_enabled": True,
            "details_submitted": True,
        })
        refresh_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/providers/stripe/refresh",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {provider_key}",
            },
        )
        with urllib.request.urlopen(refresh_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["stripe_onboarding_status"], "ready")
            self.assertTrue(data["payouts_enabled"])

        status_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/providers/status",
            headers={"Authorization": f"Bearer {provider_key}"},
        )
        with urllib.request.urlopen(status_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["provider_node_id"], "node_gateway_provider")
            self.assertIn("balance_micro_units", data)

        admin_providers_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/admin/providers",
            headers={"Authorization": "Bearer cm_admin_gateway_test"},
        )
        with urllib.request.urlopen(admin_providers_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            provider_ids = {row["provider_node_id"] for row in data["data"]}
            self.assertIn("node_gateway_provider", provider_ids)

    def test_admin_provider_settlement_endpoint(self) -> None:
        provider_id = "node_gateway_ready"
        GatewayHandler.account_store.upsert_provider(provider_node_id=provider_id)
        GatewayHandler.account_store.attach_stripe_account(
            provider_node_id=provider_id,
            stripe_connected_account_id="acct_gateway_ready",
        )
        GatewayHandler.account_store.update_stripe_account_status(
            provider_node_id=provider_id,
            onboarding_status="ready",
            charges_enabled=True,
            payouts_enabled=True,
            details_submitted=True,
        )
        GatewayHandler.ledger.deposit_customer_credits(
            customer_account_id="cust_gateway_settle",
            amount_micro_units=50_000_000,
            payment_reference="gateway_settle_dep",
        )
        GatewayHandler.ledger.record_job_execution(
            job_id="gateway_settle_job",
            customer_account_id="cust_gateway_settle",
            provider_shares=[(provider_id, 1.0)],
            model_id="llama/llama-3.1-70b-instruct",
            prompt_tokens=15000,
            completion_tokens=15000,
        )
        payable = GatewayHandler.ledger.get_balance(f"provider:{provider_id}")
        settlement_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/admin/settlements/provider",
            data=json.dumps({"provider_node_id": provider_id}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer cm_admin_gateway_test",
            },
        )
        with urllib.request.urlopen(settlement_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["amount_micro_units"], payable)
            self.assertTrue(data["stripe_transfer_id"].startswith("tr_gateway_"))
        self.assertEqual(GatewayHandler.ledger.get_balance(f"provider:{provider_id}"), 0)

        settlements_req = urllib.request.Request(
            "http://127.0.0.1:18000/v1/admin/settlements?status=completed&limit=10",
            headers={"Authorization": "Bearer cm_admin_gateway_test"},
        )
        with urllib.request.urlopen(settlements_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            settlement_ids = {row["settlement_id"] for row in data["data"]}
            self.assertIn(f"settle_provider_{provider_id}_{payable}", settlement_ids)


if __name__ == "__main__":
    unittest.main()
