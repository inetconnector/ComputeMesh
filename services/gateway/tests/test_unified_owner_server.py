"""Tests for the explicit fail-closed unified owner gateway entrypoint."""
import base64
import os
import tempfile
import unittest
from pathlib import Path

from services.billing.accounting import AccountingStore
from services.billing.owner_accounts import OwnerAccountStore
from services.billing.owner_gateway_ledger import GatewayOwnerCreditLedger
from services.billing.owner_settlement import OwnerSettlementExecutor, PayoutCapableOwnerLedger
from services.gateway.auth import GatewayAuthManager
from services.gateway.owner_inference import UnifiedOwnerInferenceEngine
from services.gateway.owner_promo_routes import UnifiedOwnerPromoRoutes
from services.gateway.owner_provider_routes import UnifiedOwnerProviderRoutesHandler
from services.gateway.owner_server import build_unified_owner_handler
from services.gateway.teaser import TeaserQuotaManager


_ENV_NAMES = (
    "COMPUTEMESH_UNIFIED_OWNER_CREDITS",
    "COMPUTEMESH_LEDGER_PATH",
    "COMPUTEMESH_OWNER_ACCOUNT_DB_PATH",
    "COMPUTEMESH_ACCOUNTING_DB_PATH",
    "COMPUTEMESH_INFERENCE_BACKEND",
    "COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE",
    "COMPUTEMESH_API_KEYS",
    "COMPUTEMESH_OWNER_PROMO_ONBOARDING",
    "COMPUTEMESH_PROMO_CONTROL_PLANE_URL",
    "COMPUTEMESH_PROMO_CONTROL_PLANE_TOKEN",
    "COMPUTEMESH_PROMO_CONTROL_PLANE_TIMEOUT",
    "COMPUTEMESH_PROMO_CONTROL_PLANE_CA_FILE",
    "COMPUTEMESH_PROMO_DECISION_TRUSTED_KEYS_JSON",
    "COMPUTEMESH_PROMO_DECISION_KEY_ID",
    "COMPUTEMESH_PROMO_DECISION_PUBLIC_KEY_B64U",
    "STRIPE_API_KEY",
    "STRIPE_WEBHOOK_SECRET",
)


class TestUnifiedOwnerServer(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_env = {name: os.environ.get(name) for name in _ENV_NAMES}
        for name in _ENV_NAMES:
            os.environ.pop(name, None)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        for name, value in self.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp_dir.cleanup()

    def _configure(self) -> None:
        os.environ["COMPUTEMESH_UNIFIED_OWNER_CREDITS"] = "1"
        os.environ["COMPUTEMESH_LEDGER_PATH"] = str(self.root / "ledger.jsonl")
        os.environ["COMPUTEMESH_OWNER_ACCOUNT_DB_PATH"] = str(self.root / "owners.sqlite3")
        os.environ["COMPUTEMESH_ACCOUNTING_DB_PATH"] = str(self.root / "accounting.sqlite3")
        os.environ["COMPUTEMESH_INFERENCE_BACKEND"] = "synthetic"
        os.environ["COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE"] = "1"

    def _configure_promo(self) -> None:
        os.environ["COMPUTEMESH_OWNER_PROMO_ONBOARDING"] = "1"
        os.environ["COMPUTEMESH_PROMO_CONTROL_PLANE_URL"] = "http://127.0.0.1:9999"
        os.environ["COMPUTEMESH_PROMO_CONTROL_PLANE_TOKEN"] = (
            "private-control-plane-promo-token-123456"
        )
        os.environ["COMPUTEMESH_PROMO_DECISION_KEY_ID"] = "promo-test-key"
        os.environ["COMPUTEMESH_PROMO_DECISION_PUBLIC_KEY_B64U"] = (
            base64.urlsafe_b64encode(b"k" * 32).rstrip(b"=").decode("ascii")
        )

    def test_owner_server_requires_explicit_enable_flag(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            build_unified_owner_handler()

    def test_owner_server_requires_all_durable_paths(self) -> None:
        os.environ["COMPUTEMESH_UNIFIED_OWNER_CREDITS"] = "1"
        with self.assertRaisesRegex(RuntimeError, "COMPUTEMESH_LEDGER_PATH"):
            build_unified_owner_handler()

        os.environ["COMPUTEMESH_LEDGER_PATH"] = str(self.root / "ledger.jsonl")
        with self.assertRaisesRegex(RuntimeError, "COMPUTEMESH_OWNER_ACCOUNT_DB_PATH"):
            build_unified_owner_handler()

        os.environ["COMPUTEMESH_OWNER_ACCOUNT_DB_PATH"] = str(self.root / "owners.sqlite3")
        with self.assertRaisesRegex(RuntimeError, "COMPUTEMESH_ACCOUNTING_DB_PATH"):
            build_unified_owner_handler()

    def test_configured_owner_server_builds_owner_aware_subsystems(self) -> None:
        self._configure()
        handler = build_unified_owner_handler()

        self.assertIsInstance(handler.ledger, PayoutCapableOwnerLedger)
        self.assertIsInstance(handler.owner_account_store, OwnerAccountStore)
        self.assertIsInstance(handler.account_store, AccountingStore)
        self.assertIsInstance(handler.auth_manager, GatewayAuthManager)
        self.assertIsInstance(handler.provider_routes, UnifiedOwnerProviderRoutesHandler)
        self.assertIsInstance(handler.inference_engine, UnifiedOwnerInferenceEngine)
        self.assertIsInstance(handler.settlement_executor, OwnerSettlementExecutor)
        self.assertIs(handler.provider_routes.settlement_executor, handler.settlement_executor)
        self.assertIsNone(handler.promo_routes)

    def test_promo_onboarding_requires_explicit_complete_operator_configuration(self) -> None:
        self._configure()
        os.environ["COMPUTEMESH_OWNER_PROMO_ONBOARDING"] = "1"
        with self.assertRaisesRegex(RuntimeError, "CONTROL_PLANE_URL"):
            build_unified_owner_handler()

        self._configure_promo()
        handler = build_unified_owner_handler()
        self.assertIsInstance(handler.promo_routes, UnifiedOwnerPromoRoutes)

    def test_provider_registration_binds_node_to_authenticated_owner(self) -> None:
        ledger = GatewayOwnerCreditLedger(storage_path=self.root / "ledger.jsonl")
        owners = OwnerAccountStore(self.root / "owners.sqlite3")
        accounts = AccountingStore(self.root / "accounting.sqlite3")
        teaser = TeaserQuotaManager(max_requests=5, max_tokens=1000)
        token = "cm_provider_rig_alpha_01"
        auth = GatewayAuthManager(
            ledger=ledger,
            teaser_manager=teaser,
            api_keys={token: "alice"},
            owner_account_store=owners,
        )
        routes = UnifiedOwnerProviderRoutesHandler(
            owner_account_store=owners,
            account_store=accounts,
            settlement_executor=None,
            auth_manager=auth,
            ledger=ledger,
        )

        payload, error, status = routes.handle_register(
            {"Authorization": f"Bearer {token}"},
            {"display_name": "Alice rig"},
        )
        self.assertIsNone(error)
        self.assertEqual(int(status), 200)
        assert payload is not None
        self.assertEqual(payload["provider_node_id"], "rig_alpha_01")
        self.assertEqual(payload["owner_id"], "alice")
        self.assertEqual(owners.owner_for_provider_node("rig_alpha_01"), "alice")
        self.assertEqual(ledger.get_owner_balances("alice").total_spendable_micro_units, 0)

    def test_provider_node_cannot_be_rebound_to_second_owner(self) -> None:
        ledger = GatewayOwnerCreditLedger(storage_path=self.root / "ledger.jsonl")
        owners = OwnerAccountStore(self.root / "owners.sqlite3")
        accounts = AccountingStore(self.root / "accounting.sqlite3")
        teaser = TeaserQuotaManager(max_requests=5, max_tokens=1000)
        owners.ensure_owner("alice")
        owners.bind_provider_node("alice", "rig_alpha_01")
        token = "cm_provider_rig_alpha_01"
        auth = GatewayAuthManager(
            ledger=ledger,
            teaser_manager=teaser,
            api_keys={token: "bob"},
            owner_account_store=owners,
        )
        routes = UnifiedOwnerProviderRoutesHandler(
            owner_account_store=owners,
            account_store=accounts,
            settlement_executor=None,
            auth_manager=auth,
            ledger=ledger,
        )

        payload, error, status = routes.handle_register(
            {"Authorization": f"Bearer {token}"},
            {},
        )
        self.assertIsNone(payload)
        self.assertEqual(int(status), 409)
        self.assertIn("another account", error or "")
        self.assertEqual(owners.owner_for_provider_node("rig_alpha_01"), "alice")


if __name__ == "__main__":
    unittest.main()
