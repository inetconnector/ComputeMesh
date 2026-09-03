from __future__ import annotations
from datetime import UTC, datetime, timedelta
import unittest

from protocol.confidential_request_contract import create_committed_session_attestation_nonce
from services.attestation.confidential_verifier import (
    ConfidentialAttestationError,
    verify_confidential_attestation,
)


class ConfidentialVerifierTests(unittest.TestCase):
    def record(self):
        now = datetime.now(UTC)
        return {
            "schema_version": 1,
            "node_id": "n1",
            "technology": "vendor-tee-v1",
            "measurement": "m",
            "runtime_digest": "sha256:x",
            "ephemeral_public_key": "pk",
            "nonce": "nonce",
            "issued_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "debug_disabled": True,
        }

    def session_record(self):
        record = self.record()
        record.update(
            {
                "account_id": "acct-1",
                "job_id": "job-1",
                "model_id": "model-1",
                "max_prompt_tokens": 1024,
                "max_completion_tokens": 128,
                "metering_public_key": "meter-key",
                "data_plane_tls_sha256": "sha256:" + "a" * 64,
                "privacy_class": "CONFIDENTIAL",
                "operation": "chat_completion",
            }
        )
        record["nonce"] = create_committed_session_attestation_nonce(
            account_id=record["account_id"],
            job_id=record["job_id"],
            model_id=record["model_id"],
            max_prompt_tokens=record["max_prompt_tokens"],
            max_completion_tokens=record["max_completion_tokens"],
            node_id=record["node_id"],
            runtime_digest=record["runtime_digest"],
            recipient_public_key=record["ephemeral_public_key"],
            metering_public_key=record["metering_public_key"],
            data_plane_tls_sha256=record["data_plane_tls_sha256"],
            privacy_class=record["privacy_class"],
            operation=record["operation"],
            entropy=b"q" * 32,
        )
        return record

    def test_unregistered_technology_fails_closed(self):
        self.assertFalse(verify_confidential_attestation(self.record(), verifiers={}).verified)

    def test_nonce_replay_binding_is_rejected(self):
        self.assertFalse(
            verify_confidential_attestation(
                self.record(),
                verifiers={"vendor-tee-v1": lambda _: True},
                expected_nonce="other",
            ).verified
        )

    def test_concrete_registered_verifier_can_accept(self):
        self.assertTrue(
            verify_confidential_attestation(
                self.record(),
                verifiers={"vendor-tee-v1": lambda _: True},
                expected_node_id="n1",
                expected_nonce="nonce",
            ).verified
        )

    def test_debug_enabled_is_rejected(self):
        record = self.record()
        record["debug_disabled"] = False
        self.assertFalse(
            verify_confidential_attestation(
                record,
                verifiers={"vendor-tee-v1": lambda _: True},
            ).verified
        )

    def test_cmrc2_complete_session_commitment_is_accepted(self):
        record = self.session_record()
        result = verify_confidential_attestation(
            record,
            verifiers={"vendor-tee-v1": lambda _: True},
            expected_node_id="n1",
            expected_nonce=record["nonce"],
        )
        self.assertTrue(result.verified)

    def test_cmrc2_outer_key_substitution_is_rejected_before_vendor_acceptance(self):
        record = self.session_record()
        record["ephemeral_public_key"] = "attacker-key"
        with self.assertRaisesRegex(ConfidentialAttestationError, "session commitment"):
            verify_confidential_attestation(
                record,
                verifiers={"vendor-tee-v1": lambda _: True},
                expected_node_id="n1",
                expected_nonce=record["nonce"],
            )


if __name__ == "__main__":
    unittest.main()
