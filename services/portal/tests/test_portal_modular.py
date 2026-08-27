"""Unit tests for modular portal registration and quotes handlers."""
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
from services.portal.routes_registration import CURRENT_TERMS_VERSION, PortalRegistrationHandler


def accepted_registration(**overrides):
    body = {
        "email": "consumer@computemesh.test",
        "role": "consumer",
        "accepted_terms": True,
        "privacy_acknowledged": True,
        "business_user": True,
        "terms_version": CURRENT_TERMS_VERSION,
    }
    body.update(overrides)
    return body


def accepted_provider(**overrides):
    body = accepted_registration(
        email="provider@computemesh.test",
        role="provider",
        country_code="DE",
        provider_data_processing_terms_accepted=True,
        no_prompt_logging_attested=True,
    )
    body.update(overrides)
    return body


class TestPortalModular(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        self.reg_handler = PortalRegistrationHandler(store=self.store)
        self.quotes_handler = PortalQuotesHandler()

    def test_registration_rejects_missing_clickwrap_acceptance(self) -> None:
        res, err, status = self.reg_handler.handle_register({
            "email": "consumer@computemesh.test",
            "role": "consumer",
        })
        self.assertIsNone(res)
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("Acceptance of Terms", err or "")

    def test_registration_rejects_non_business_user(self) -> None:
        body = accepted_registration(business_user=False)
        res, err, status = self.reg_handler.handle_register(body)
        self.assertIsNone(res)
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertIn("business users", err or "")

    def test_consumer_registration(self) -> None:
        res, err, status = self.reg_handler.handle_register(accepted_registration())
        self.assertIsNone(err)
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertIsNotNone(res)
        self.assertTrue(res["api_key"].startswith("cm_live_"))
        self.assertEqual(res["free_credit_granted_usd"], 10.0)
        self.assertEqual(res["terms_version"], CURRENT_TERMS_VERSION)
        stored = self.store[res["api_key"]]
        self.assertEqual(DEFAULT_VAULT.decrypt(stored["email_encrypted"]), "consumer@computemesh.test")
        self.assertTrue(stored["business_user_confirmed"])
        self.assertEqual(stored["terms_version"], CURRENT_TERMS_VERSION)

    def test_provider_registration_requires_eea_and_data_obligations(self) -> None:
        res, err, status = self.reg_handler.handle_register(accepted_provider(country_code="US"))
        self.assertIsNone(res)
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertIn("EEA", err or "")

        res, err, status = self.reg_handler.handle_register(
            accepted_provider(provider_data_processing_terms_accepted=False)
        )
        self.assertIsNone(res)
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("data-processing", err or "")

    def test_provider_registration_is_not_node_admission(self) -> None:
        res, err, status = self.reg_handler.handle_register(accepted_provider())
        self.assertIsNone(err)
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertIsNotNone(res)
        self.assertTrue(res["api_key"].startswith("cm_provider_"))
        self.assertFalse(res["production_node_eligible"])
        stored = self.store[res["api_key"]]
        self.assertEqual(stored["country_code"], "DE")
        self.assertFalse(stored["production_node_eligible"])
        self.assertTrue(stored["provider_data_processing_terms_accepted_at"].endswith("Z"))
        self.assertTrue(stored["no_prompt_logging_attested_at"].endswith("Z"))

    def test_registration_persists_terms_acceptance_with_gateway_api_key_store(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "api_keys.json"
            os.environ["COMPUTEMESH_API_KEY_STORE_PATH"] = str(path)
            try:
                res, err, status = self.reg_handler.handle_register(accepted_registration(
                    email="store@computemesh.test",
                ))
            finally:
                os.environ.pop("COMPUTEMESH_API_KEY_STORE_PATH", None)
            self.assertIsNone(err)
            self.assertEqual(status, HTTPStatus.CREATED)
            self.assertIsNotNone(res)
            data = json.loads(path.read_text(encoding="utf-8"))
            stored = data["keys"][0]
            self.assertEqual(stored["api_key"], res["api_key"])
            self.assertEqual(stored["account_id"], res["account_id"])
            self.assertEqual(stored["terms_version"], CURRENT_TERMS_VERSION)
            self.assertTrue(stored["business_user_confirmed"])
            self.assertTrue(stored["terms_accepted_at"].endswith("Z"))

    def test_public_quote_is_explicitly_non_binding(self) -> None:
        res, err, status = self.quotes_handler.handle_quote({
            "tokens_million": 100.0,
            "model_tier": "70b",
        })
        self.assertIsNone(err)
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIsNotNone(res)
        self.assertEqual(res["kind"], "illustrative_estimate")
        self.assertFalse(res["binding"])
        self.assertIn("illustrative_total_usd", res)
        self.assertNotIn("savings_percent", res)
        self.assertNotIn("cloud_equivalent_usd", res)


if __name__ == "__main__":
    unittest.main()
