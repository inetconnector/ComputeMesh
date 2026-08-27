from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.billing.crypto_payments import CryptoPaymentError, CryptoPaymentService
from services.billing.ledger import Ledger
from services.compliance.policy import (
    ProductionComplianceError,
    ProviderComplianceRegistry,
    assert_production_launch_gate,
    require_production_model_attribution,
)


class CompliancePolicyTests(unittest.TestCase):
    def _registry(self, *, country: str = "DE", status: str = "active") -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = Path(td.name) / "providers.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "providers": [
                        {
                            "node_id": "node-a",
                            "country_code": country,
                            "business_verified": True,
                            "status": status,
                            "provider_terms_version": "2.1",
                            "provider_terms_accepted": True,
                            "data_processing_terms_accepted": True,
                            "no_prompt_logging_attested": True,
                            "payment_processor": "stripe_connect",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_provider_registry_accepts_only_eligible_eea_node(self) -> None:
        registry = ProviderComplianceRegistry.from_path(self._registry())
        self.assertEqual(registry.require_eligible("node-a").country_code, "DE")
        with self.assertRaises(ProductionComplianceError):
            ProviderComplianceRegistry.from_path(self._registry(country="US")).require_eligible("node-a")

    def test_launch_gate_is_fail_closed_in_production(self) -> None:
        with patch.dict(os.environ, {"COMPUTEMESH_PRODUCTION_MODE": "1"}, clear=True):
            with self.assertRaises(ProductionComplianceError):
                assert_production_launch_gate()

    def test_launch_gate_accepts_complete_control_set(self) -> None:
        registry = self._registry()
        env = {
            "COMPUTEMESH_PRODUCTION_MODE": "1",
            "COMPUTEMESH_LEGAL_REVIEW_APPROVED": "1",
            "COMPUTEMESH_DPA_READY": "1",
            "COMPUTEMESH_PROVIDER_AGREEMENT_READY": "1",
            "COMPUTEMESH_SUBPROCESSOR_REGISTER_COMPLETE": "1",
            "COMPUTEMESH_TRANSFER_ASSESSMENT_COMPLETE": "1",
            "COMPUTEMESH_PAYMENT_PROVIDER": "stripe",
            "COMPUTEMESH_PROVIDER_COMPLIANCE_REGISTRY": str(registry),
        }
        with patch.dict(os.environ, env, clear=True):
            assert_production_launch_gate()

    def test_production_model_requires_upstream_attribution(self) -> None:
        with patch.dict(os.environ, {"COMPUTEMESH_PRODUCTION_MODE": "1"}, clear=True):
            with self.assertRaises(ProductionComplianceError):
                require_production_model_attribution({"license": {"id": "apache-2.0", "source": "x"}})
            require_production_model_attribution(
                {
                    "upstream": {"publisher": "Qwen", "model_name": "Qwen2.5", "source": "https://example.test"},
                    "license": {"id": "apache-2.0", "source": "https://example.test/license"},
                }
            )

    def test_direct_crypto_crediting_is_disabled_in_production(self) -> None:
        with patch.dict(os.environ, {"COMPUTEMESH_PRODUCTION_MODE": "1"}, clear=True):
            with self.assertRaises(CryptoPaymentError):
                CryptoPaymentService(Ledger())


if __name__ == "__main__":
    unittest.main()
