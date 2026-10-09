"""Tests for the opt-in gateway billing bridge used by agent workers."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.billing.ledger import Ledger
from services.common.pricing import calculate_token_charge_micro
from services.gateway.agent_billing import (
    AgentBillingError,
    AgentBillingEvidenceStore,
    GatewayAgentBilling,
)
from services.gateway.inference_backend import BackendResult
from services.mcp.platform.model_caller import MeshDispatchModelCaller


class GatewayAgentBillingTests(unittest.TestCase):
    def _billing(self, root: Path) -> tuple[Ledger, GatewayAgentBilling]:
        ledger = Ledger(root / "ledger.jsonl")
        ledger.deposit_customer_credits(
            customer_account_id="customer-1",
            amount_micro_units=100_000_000,
            payment_reference="billing-adapter-test",
        )
        return ledger, GatewayAgentBilling(
            ledger,
            model_id="qwen2.5:3b",
            max_tokens=32,
            max_iterations=2,
        )

    def test_capture_is_idempotent_and_uses_verified_provider_shares(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ledger, billing = self._billing(Path(raw))
            reservation = billing.reserve(
                SimpleNamespace(principal_id="customer-1"),
                SimpleNamespace(turn_id="turn-1"),
            )
            billing.observe(BackendResult(
                "answer",
                4_000,
                6_000,
                execution_job_id="job-1",
                provider_shares=(("node-a", 0.25), ("node-b", 0.75)),
            ))
            billing.settle(reservation, SimpleNamespace())
            expected = calculate_token_charge_micro("qwen2.5:3b", 4_000, 6_000)
            self.assertEqual(ledger.get_hold(reservation.hold_id).status, "captured")
            self.assertEqual(ledger.get_balance("customer-1"), 100_000_000 - expected)
            balance_after_capture = ledger.get_balance("customer-1")
            billing.settle(reservation, SimpleNamespace())
            self.assertEqual(ledger.get_balance("customer-1"), balance_after_capture)
            self.assertGreater(ledger.get_balance("provider:node-a"), 0)
            self.assertGreater(ledger.get_balance("provider:node-b"), 0)

    def test_failed_or_unmetered_turn_releases_the_hold(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ledger, billing = self._billing(Path(raw))
            reservation = billing.reserve(
                SimpleNamespace(principal_id="customer-1"),
                SimpleNamespace(turn_id="turn-2"),
            )
            billing.release(reservation, RuntimeError("backend stopped"))
            self.assertEqual(ledger.get_hold(reservation.hold_id).status, "released")

            second = GatewayAgentBilling(
                ledger,
                model_id="qwen2.5:3b",
                max_tokens=32,
                max_iterations=2,
            )
            reservation = second.reserve(
                SimpleNamespace(principal_id="customer-1"),
                SimpleNamespace(turn_id="turn-3"),
            )
            second.settle(reservation, SimpleNamespace())
            self.assertEqual(ledger.get_hold(reservation.hold_id).status, "released")

    def test_missing_provider_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ledger, billing = self._billing(Path(raw))
            reservation = billing.reserve(
                SimpleNamespace(principal_id="customer-1"),
                SimpleNamespace(turn_id="turn-4"),
            )
            with self.assertRaises(AgentBillingError):
                billing.observe(BackendResult("answer", 1, 1, execution_job_id="job-2"))
            billing.release(reservation, AgentBillingError("missing evidence"))
            self.assertEqual(ledger.get_hold(reservation.hold_id).status, "released")

    def test_verified_evidence_survives_billing_adapter_restart(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger, _unused = self._billing(root)
            evidence_path = root / "agent-evidence.sqlite3"
            first_store = AgentBillingEvidenceStore(evidence_path)
            first = GatewayAgentBilling(
                ledger,
                model_id="qwen2.5:3b",
                max_tokens=32,
                max_iterations=2,
                evidence_store=first_store,
            )
            reservation = first.reserve(
                SimpleNamespace(principal_id="customer-1"),
                SimpleNamespace(turn_id="turn-restart"),
            )
            first.observe(BackendResult(
                "answer",
                4_000,
                6_000,
                execution_job_id="job-restart",
                provider_shares=(("node-a", 1.0),),
            ))
            first_store.close()

            second_store = AgentBillingEvidenceStore(evidence_path)
            try:
                second = GatewayAgentBilling(
                    ledger,
                    model_id="qwen2.5:3b",
                    max_tokens=32,
                    max_iterations=2,
                    evidence_store=second_store,
                )
                resumed = second.reserve(
                    SimpleNamespace(principal_id="customer-1"),
                    SimpleNamespace(turn_id="turn-restart"),
                )
                second.settle(resumed, SimpleNamespace())
                expected = calculate_token_charge_micro("qwen2.5:3b", 4_000, 6_000)
                self.assertEqual(ledger.get_balance("customer-1"), 100_000_000 - expected)
                self.assertEqual(ledger.get_hold(reservation.hold_id).status, "captured")
            finally:
                second_store.close()

    def test_mesh_caller_evidence_can_settle_existing_gateway_ledger(self) -> None:
        class DispatchResult:
            node_id = "node-mesh"
            lease = SimpleNamespace(lease_id="lease-mesh")

            response = {
                "output": "mesh answer",
                "usage": {"prompt_tokens": 4, "completion_tokens": 6},
            }

        class Dispatcher:
            def dispatch(self, **_kwargs):
                return DispatchResult()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger = Ledger(root / "ledger.jsonl")
            ledger.deposit_customer_credits(
                customer_account_id="customer-1",
                amount_micro_units=100_000_000,
                payment_reference="mesh-billing-test",
            )
            billing = GatewayAgentBilling(
                ledger,
                model_id="qwen2.5:3b",
                max_tokens=32,
                max_iterations=2,
            )
            reservation = billing.reserve(
                SimpleNamespace(principal_id="customer-1"),
                SimpleNamespace(turn_id="turn-mesh-billing"),
            )
            caller = MeshDispatchModelCaller(
                Dispatcher(),
                session_id="session-1",
                turn_id="turn-mesh-billing",
                model_id="qwen2.5:3b",
                result_observer=billing.observe,
            )
            caller([{"role": "user", "content": "hello"}], [])
            billing.settle(reservation, SimpleNamespace())
            expected = calculate_token_charge_micro("qwen2.5:3b", 4, 6)
            self.assertEqual(ledger.get_balance("customer-1"), 100_000_000 - expected)
            self.assertEqual(ledger.get_hold(reservation.hold_id).status, "captured")


if __name__ == "__main__":
    unittest.main()
