from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    create_confidential_request,
    encrypt_response_in_attested_recipient,
    generate_attested_recipient_keypair,
)
from protocol.confidential_metering import (
    ConfidentialMeteringError,
    generate_attested_metering_keypair,
    sign_confidential_usage,
)
from protocol.confidential_request_contract import create_committed_attestation_nonce
from runtime.confidential.data_plane import (
    AttestedConfidentialEndpoint,
    ConfidentialDataPlaneResult,
)
from runtime.confidential.session import (
    ConfidentialSessionProvision,
    SQLiteConfidentialSessionStore,
)
from services.billing.confidential_owner_ledger import PayoutCapableConfidentialOwnerLedger
from services.billing.owner_credits import owner_bucket_account
from services.gateway.confidential_coordinator import (
    ConfidentialCoordinatorError,
    ConfidentialInferenceCoordinator,
)


class _Broker:
    def __init__(self, *, account_id: str, model_id: str, node_id: str = "node-foreign") -> None:
        self.account_id = account_id
        self.model_id = model_id
        self.node_id = node_id
        self.recipient_private, self.recipient_public = generate_attested_recipient_keypair()
        self.metering_private, self.metering_public = generate_attested_metering_keypair()
        self.job_index = 0

    def provision(
        self,
        *,
        account_id: str,
        model_id: str,
        privacy_class: str,
        operation: str,
        max_prompt_tokens: int,
        max_completion_tokens: int,
    ) -> ConfidentialSessionProvision:
        self.job_index += 1
        job_id = f"job-conf-{self.job_index}"
        nonce = create_committed_attestation_nonce(
            model_id=model_id,
            max_prompt_tokens=max_prompt_tokens,
            max_completion_tokens=max_completion_tokens,
        )
        runtime = "sha256:" + "b" * 64
        tls = "sha256:" + "c" * 64
        endpoint = AttestedConfidentialEndpoint(
            url="https://provider.example/v1/confidential/execute",
            node_id=self.node_id,
            runtime_digest=runtime,
            attestation_nonce=nonce,
            recipient_public_key=self.recipient_public,
            metering_public_key=self.metering_public,
            tls_certificate_sha256=tls,
        )
        now = datetime.now(UTC)
        attestation = {
            "schema_version": 1,
            "node_id": self.node_id,
            "technology": "test-tee",
            "measurement": "measurement-test",
            "runtime_digest": runtime,
            "ephemeral_public_key": self.recipient_public,
            "metering_public_key": self.metering_public,
            "data_plane_tls_sha256": tls,
            "nonce": nonce,
            "issued_at": (now - timedelta(seconds=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "debug_disabled": True,
        }
        return ConfidentialSessionProvision(
            job_id=job_id,
            account_id=account_id,
            model_id=model_id,
            privacy_class=privacy_class,
            operation=operation,
            max_prompt_tokens=max_prompt_tokens,
            max_completion_tokens=max_completion_tokens,
            endpoint=endpoint,
            attestation=attestation,
            expires_at=(now + timedelta(minutes=5)).isoformat(),
        )


class ConfidentialCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.ledger_path = root / "ledger.jsonl"
        self.session_path = root / "sessions.sqlite3"
        self.customer = "customer-owner"
        self.provider_owner = "provider-owner"
        self.model = "qwen/qwen2.5-7b-instruct"
        self.broker = _Broker(account_id=self.customer, model_id=self.model)
        self.ledger = PayoutCapableConfidentialOwnerLedger(storage_path=self.ledger_path)
        self.sessions = SQLiteConfidentialSessionStore(self.session_path)
        self.ledger.deposit_owner_purchased_credits(
            owner_id=self.customer,
            amount_micro_units=5_000_000,
            payment_reference="seed-customer",
        )
        self.provider_owners = {self.broker.node_id: self.provider_owner}
        self.coordinator = self._coordinator(self.ledger, self.sessions)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _coordinator(self, ledger, sessions):
        return ConfidentialInferenceCoordinator(
            ledger=ledger,
            session_store=sessions,
            broker=self.broker,
            provider_owner_resolver=lambda node_id: self.provider_owners.get(node_id, ""),
            marketplace_fee_bps=2500,
            self_compute_fee_bps=1000,
        )

    @staticmethod
    def _binding(admission) -> ConfidentialBinding:
        session = admission.session
        return ConfidentialBinding(
            account_id=session.account_id,
            job_id=session.job_id,
            node_id=session.node_id,
            attestation_nonce=session.attestation_nonce,
            runtime_digest=session.runtime_digest,
            data_plane_tls_sha256=session.data_plane_tls_sha256,
            privacy_class=session.privacy_class,
            operation=session.operation,
        )

    def _dispatch_and_result(
        self,
        admission,
        *,
        prompt_tokens: int = 800,
        completion_tokens: int = 200,
        meter_private=None,
    ):
        envelope, client_context = create_confidential_request(
            b'{"messages":[{"role":"user","content":"opaque-to-gateway"}]}',
            recipient_public_key=admission.session.recipient_public_key,
            binding=self._binding(admission),
        )
        client_context.close()
        session = self.sessions.begin_dispatch(
            job_id=admission.session.job_id,
            account_id=self.customer,
            envelope_id=envelope.envelope_id,
        )
        response = encrypt_response_in_attested_recipient(
            envelope,
            b'{"answer":"opaque-to-gateway"}',
            recipient_private_key=self.broker.recipient_private,
        )
        receipt = sign_confidential_usage(
            private_key=meter_private or self.broker.metering_private,
            account_id=session.account_id,
            job_id=session.job_id,
            request_envelope_id=envelope.envelope_id,
            response_id=response.response_id,
            node_id=session.node_id,
            runtime_digest=session.runtime_digest,
            privacy_class=session.privacy_class,
            operation=session.operation,
            model_id=session.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return session, ConfidentialDataPlaneResult(response=response, usage_receipt=receipt)

    def test_foreign_provider_receipt_settles_operator_and_provider_without_content(self) -> None:
        admission = self.coordinator.open_session(
            account_id=self.customer,
            model_id=self.model,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=2_000,
            max_completion_tokens=1_000,
        )
        session, result = self._dispatch_and_result(admission)
        receipt = self.coordinator.verify_and_record_metering(
            session=session,
            data_plane_result=result,
        )
        settlement = self.coordinator.settle_metered_session(job_id=session.job_id)
        self.assertEqual(settlement.receipt.receipt_id, receipt.receipt_id)
        self.assertEqual(settlement.session.state, "COMPLETED")
        self.assertGreater(settlement.quote.operator_fee_micro_units, 0)
        self.assertGreater(
            self.ledger.get_balance(owner_bucket_account(self.provider_owner, "earned")),
            0,
        )
        self.assertGreater(self.ledger.get_balance("revenue:network_fee"), 0)
        self.assertEqual(self.ledger.reconcile()["status"], "balanced")
        encoded = repr(settlement)
        self.assertNotIn("opaque-to-gateway", encoded)

    def test_metered_restart_recovery_is_idempotent(self) -> None:
        admission = self.coordinator.open_session(
            account_id=self.customer,
            model_id=self.model,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=2_000,
            max_completion_tokens=1_000,
        )
        session, result = self._dispatch_and_result(admission)
        self.coordinator.verify_and_record_metering(session=session, data_plane_result=result)
        self.assertEqual(self.sessions.get(session.job_id).state, "METERED")  # type: ignore[union-attr]

        restarted_ledger = PayoutCapableConfidentialOwnerLedger(storage_path=self.ledger_path)
        restarted_sessions = SQLiteConfidentialSessionStore(self.session_path)
        restarted = self._coordinator(restarted_ledger, restarted_sessions)
        recovered = restarted.reconcile_metered()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].session.state, "COMPLETED")
        provider_balance = restarted_ledger.get_balance(
            owner_bucket_account(self.provider_owner, "earned")
        )
        again = restarted.settle_metered_session(job_id=session.job_id)
        self.assertEqual(again.session.state, "COMPLETED")
        self.assertEqual(
            restarted_ledger.get_balance(owner_bucket_account(self.provider_owner, "earned")),
            provider_balance,
        )
        self.assertEqual(restarted_ledger.reconcile()["status"], "balanced")

    def test_wrong_metering_key_is_rejected_before_metered_checkpoint(self) -> None:
        admission = self.coordinator.open_session(
            account_id=self.customer,
            model_id=self.model,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=2_000,
            max_completion_tokens=1_000,
        )
        wrong_private, _ = generate_attested_metering_keypair()
        session, result = self._dispatch_and_result(admission, meter_private=wrong_private)
        with self.assertRaises(ConfidentialMeteringError):
            self.coordinator.verify_and_record_metering(
                session=session,
                data_plane_result=result,
            )
        self.assertEqual(self.sessions.get(session.job_id).state, "DISPATCHED")  # type: ignore[union-attr]

    def test_receipt_token_count_over_reserved_limit_is_rejected(self) -> None:
        admission = self.coordinator.open_session(
            account_id=self.customer,
            model_id=self.model,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=1_000,
            max_completion_tokens=500,
        )
        session, result = self._dispatch_and_result(
            admission,
            prompt_tokens=1_001,
            completion_tokens=1,
        )
        with self.assertRaisesRegex(ConfidentialMeteringError, "prompt token"):
            self.coordinator.verify_and_record_metering(
                session=session,
                data_plane_result=result,
            )

    def test_self_compute_still_pays_nonzero_inetconnector_fee(self) -> None:
        self.provider_owners[self.broker.node_id] = self.customer
        admission = self.coordinator.open_session(
            account_id=self.customer,
            model_id=self.model,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            max_prompt_tokens=2_000,
            max_completion_tokens=1_000,
        )
        session, result = self._dispatch_and_result(admission)
        self.coordinator.verify_and_record_metering(session=session, data_plane_result=result)
        settlement = self.coordinator.settle_metered_session(job_id=session.job_id)
        self.assertTrue(settlement.quote.is_pure_self_compute)
        self.assertGreater(settlement.quote.operator_fee_micro_units, 0)
        self.assertEqual(settlement.quote.provider_earned_by_owner, ())
        self.assertEqual(
            self.ledger.get_balance(owner_bucket_account(self.customer, "earned")),
            0,
        )

    def test_unresolved_provider_owner_fails_before_reservation(self) -> None:
        self.provider_owners.clear()
        before = self.ledger.get_owner_balances(self.customer)
        with self.assertRaisesRegex(ConfidentialCoordinatorError, "unresolved"):
            self.coordinator.open_session(
                account_id=self.customer,
                model_id=self.model,
                privacy_class="CONFIDENTIAL",
                operation="chat_completion",
                max_prompt_tokens=2_000,
                max_completion_tokens=1_000,
            )
        after = self.ledger.get_owner_balances(self.customer)
        self.assertEqual(after.total_spendable_micro_units, before.total_spendable_micro_units)

    def test_unbound_broker_nonce_fails_before_reservation(self) -> None:
        class BadBroker(_Broker):
            def provision(self, **kwargs):
                provision = super().provision(**kwargs)
                wrong_nonce = create_committed_attestation_nonce(
                    model_id="other-model",
                    max_prompt_tokens=kwargs["max_prompt_tokens"],
                    max_completion_tokens=kwargs["max_completion_tokens"],
                )
                endpoint = AttestedConfidentialEndpoint(
                    url=provision.endpoint.url,
                    node_id=provision.endpoint.node_id,
                    runtime_digest=provision.endpoint.runtime_digest,
                    attestation_nonce=wrong_nonce,
                    recipient_public_key=provision.endpoint.recipient_public_key,
                    metering_public_key=provision.endpoint.metering_public_key,
                    tls_certificate_sha256=provision.endpoint.tls_certificate_sha256,
                )
                attestation = dict(provision.attestation)
                attestation["nonce"] = wrong_nonce
                return ConfidentialSessionProvision(
                    **{
                        **provision.__dict__,
                        "endpoint": endpoint,
                        "attestation": attestation,
                    }
                )

        bad_broker = BadBroker(account_id=self.customer, model_id=self.model)
        self.provider_owners[bad_broker.node_id] = self.provider_owner
        coordinator = ConfidentialInferenceCoordinator(
            ledger=self.ledger,
            session_store=self.sessions,
            broker=bad_broker,
            provider_owner_resolver=lambda node_id: self.provider_owners.get(node_id, ""),
        )
        before = self.ledger.get_owner_balances(self.customer)
        with self.assertRaisesRegex(ConfidentialCoordinatorError, "unbound request contract"):
            coordinator.open_session(
                account_id=self.customer,
                model_id=self.model,
                privacy_class="CONFIDENTIAL",
                operation="chat_completion",
                max_prompt_tokens=2_000,
                max_completion_tokens=1_000,
            )
        after = self.ledger.get_owner_balances(self.customer)
        self.assertEqual(after.total_spendable_micro_units, before.total_spendable_micro_units)

    def test_self_compute_fee_cannot_be_configured_to_zero(self) -> None:
        with self.assertRaisesRegex(ValueError, "self_compute_fee_bps"):
            ConfidentialInferenceCoordinator(
                ledger=self.ledger,
                session_store=self.sessions,
                broker=self.broker,
                provider_owner_resolver=lambda _: self.customer,
                self_compute_fee_bps=0,
            )


if __name__ == "__main__":
    unittest.main()
