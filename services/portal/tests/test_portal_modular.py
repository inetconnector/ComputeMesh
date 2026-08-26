"""Unit tests for Modular Portal Registration and Quotes Handlers."""
from http import HTTPStatus
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.identity.vault import DEFAULT_VAULT
from services.portal.routes_quotes import PortalQuotesHandler
from services.portal.routes_registration import PortalRegistrationHandler


class TestPortalModular(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        self.reg_handler = PortalRegistrationHandler(store=self.store)
        self.quotes_handler = PortalQuotesHandler()

    def test_consumer_registration(self) -> None:
        res, err, status = self.reg_handler.handle_register({
            "email": "consumer@computemesh.test",
            "role": "consumer",
        })
        self.assertIsNone(err)
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertIsNotNone(res)
        self.assertTrue(res["api_key"].startswith("cm_live_"))
        self.assertEqual(res["free_credit_granted_usd"], 10.0)

        stored = self.store[res["api_key"]]
        self.assertEqual(DEFAULT_VAULT.decrypt(stored["email_encrypted"]), "consumer@computemesh.test")

    def test_provider_registration_with_wallet(self) -> None:
        res, err, status = self.reg_handler.handle_register({
            "email": "provider@computemesh.test",
            "role": "provider",
            "wallet": "0x1234567890abcdef1234567890abcdef12345678",
        })
        self.assertIsNone(err)
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertIsNotNone(res)
        self.assertTrue(res["api_key"].startswith("cm_provider_"))

        stored = self.store[res["api_key"]]
        self.assertEqual(DEFAULT_VAULT.decrypt(stored["wallet_encrypted"]), "0x1234567890abcdef1234567890abcdef12345678")

    def test_registration_persists_gateway_api_key_store_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "api_keys.json"
            os.environ["COMPUTEMESH_API_KEY_STORE_PATH"] = str(path)
            try:
                res, err, status = self.reg_handler.handle_register({
                    "email": "store@computemesh.test",
                    "role": "consumer",
                })
            finally:
                os.environ.pop("COMPUTEMESH_API_KEY_STORE_PATH", None)
            self.assertIsNone(err)
            self.assertEqual(status, HTTPStatus.CREATED)
            self.assertIsNotNone(res)
            data = json.loads(path.read_text(encoding="utf-8"))
            stored = data["keys"][0]
            self.assertEqual(stored["api_key"], res["api_key"])
            self.assertEqual(stored["account_id"], res["account_id"])

    def test_quotes_calculation_and_savings(self) -> None:
        res, err, status = self.quotes_handler.handle_quote({
            "tokens_million": 100.0,
            "model_tier": "70b",
        })
        self.assertIsNone(err)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIsNotNone(res)
        self.assertEqual(res["total_cost_usd"], 120.0)  # $1.20 blended * 100
        self.assertEqual(res["cloud_equivalent_usd"], 350.0)  # $3.50 * 100
        self.assertGreaterEqual(res["savings_percent"], 60.0)


if __name__ == "__main__":
    unittest.main()
