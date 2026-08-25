"""Unit tests for ComputeMesh Gateway Authentication & Entitlement Manager."""
from http import HTTPStatus
import os
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.billing.ledger import Ledger
from services.gateway.auth import (
    AuthResult,
    GatewayAuthManager,
    extract_bearer_token,
    resolve_client_ip,
)
from services.gateway.teaser import TeaserQuotaManager


class TestGatewayAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = Ledger()
        self.teaser_manager = TeaserQuotaManager(max_requests=5, max_tokens=1000)
        self.auth_manager = GatewayAuthManager(
            ledger=self.ledger,
            teaser_manager=self.teaser_manager,
            api_keys={"cm_live_registered_test_key": "cust_registered_user"},
        )

    def test_extract_bearer_token(self) -> None:
        headers_valid = {"Authorization": "Bearer cm_live_12345"}
        self.assertEqual(extract_bearer_token(headers_valid), "cm_live_12345")

        headers_no_bearer = {"Authorization": "Basic dXNlcjpwYXNz"}
        self.assertEqual(extract_bearer_token(headers_no_bearer), "")

        headers_empty = {}
        self.assertEqual(extract_bearer_token(headers_empty), "")

    def test_resolve_client_ip(self) -> None:
        headers_forwarded = {"X-Forwarded-For": "203.0.113.195, 70.41.3.18"}
        self.assertEqual(resolve_client_ip(headers_forwarded), "203.0.113.195")

        headers_real_ip = {"X-Real-IP": "198.51.100.42"}
        self.assertEqual(resolve_client_ip(headers_real_ip), "198.51.100.42")

        self.assertEqual(resolve_client_ip({}, client_address=("10.0.0.5", 48123)), "10.0.0.5")
        self.assertEqual(resolve_client_ip({}), "127.0.0.1")

    def test_authenticate_registered_customer(self) -> None:
        headers = {"Authorization": "Bearer cm_live_registered_test_key"}
        auth = self.auth_manager.authenticate_request(headers)
        self.assertTrue(auth.is_authenticated)
        self.assertEqual(auth.account_id, "cust_registered_user")
        self.assertFalse(auth.is_teaser)
        self.assertFalse(auth.is_provider_self_compute)
        self.assertFalse(auth.is_quota_exceeded)
        self.assertGreater(self.ledger.get_balance("cust_registered_user"), 0)

    def test_authenticate_dynamic_live_customer(self) -> None:
        headers = {"Authorization": "Bearer cm_live_fresh_customer_99"}
        auth = self.auth_manager.authenticate_request(headers)
        self.assertTrue(auth.is_authenticated)
        self.assertEqual(auth.account_id, "cust_fresh_customer_99")
        self.assertFalse(auth.is_teaser)
        self.assertFalse(auth.is_provider_self_compute)
        self.assertGreater(self.ledger.get_balance("cust_fresh_customer_99"), 0)

    def test_authenticate_provider_self_compute(self) -> None:
        headers = {"Authorization": "Bearer cm_provider_rig_alpha_01"}
        auth = self.auth_manager.authenticate_request(headers)
        self.assertTrue(auth.is_authenticated)
        self.assertEqual(auth.account_id, "provider_self_rig_alpha_01")
        self.assertTrue(auth.is_provider_self_compute)
        self.assertFalse(auth.is_teaser)
        self.assertGreater(self.ledger.get_balance("provider_self_rig_alpha_01"), 0)

    def test_authenticate_teaser_playground(self) -> None:
        headers = {"X-Forwarded-For": "198.51.100.77"}
        auth = self.auth_manager.authenticate_request(headers, allow_teaser=True)
        self.assertTrue(auth.is_authenticated)
        self.assertEqual(auth.account_id, "teaser_198_51_100_77")
        self.assertTrue(auth.is_teaser)
        self.assertFalse(auth.is_quota_exceeded)
        self.assertGreater(self.ledger.get_balance("teaser_198_51_100_77"), 0)

    def test_authenticate_teaser_quota_exceeded(self) -> None:
        client_ip = "198.51.100.88"
        headers = {"X-Forwarded-For": client_ip}

        # Exhaust quota of 5 requests
        for _ in range(5):
            self.teaser_manager.record_usage(client_ip)

        auth = self.auth_manager.authenticate_request(headers, allow_teaser=True)
        self.assertTrue(auth.is_authenticated)
        self.assertTrue(auth.is_teaser)
        self.assertTrue(auth.is_quota_exceeded)
        self.assertIsNone(auth.account_id)

    def test_authenticate_admin(self) -> None:
        admin_key = os.environ.get("COMPUTEMESH_ADMIN_KEY", "cm_admin_master_dani_2026")
        headers_valid = {"Authorization": f"Bearer {admin_key}"}
        is_admin, err, status = self.auth_manager.authenticate_admin(headers_valid)
        self.assertTrue(is_admin)
        self.assertIsNone(err)
        self.assertEqual(status, HTTPStatus.OK)

        headers_invalid = {"Authorization": "Bearer cm_invalid_admin"}
        is_admin, err, status = self.auth_manager.authenticate_admin(headers_invalid)
        self.assertFalse(is_admin)
        self.assertIsNotNone(err)
        self.assertEqual(status, HTTPStatus.FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
