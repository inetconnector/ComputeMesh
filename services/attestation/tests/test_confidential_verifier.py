from __future__ import annotations
from datetime import UTC, datetime, timedelta
import unittest
from services.attestation.confidential_verifier import verify_confidential_attestation


class ConfidentialVerifierTests(unittest.TestCase):
    def record(self):
        now = datetime.now(UTC)
        return {"schema_version": 1, "node_id": "n1", "technology": "vendor-tee-v1", "measurement": "m", "runtime_digest": "sha256:x", "ephemeral_public_key": "pk", "nonce": "nonce", "issued_at": (now - timedelta(minutes=1)).isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat(), "debug_disabled": True}

    def test_unregistered_technology_fails_closed(self):
        self.assertFalse(verify_confidential_attestation(self.record(), verifiers={}).verified)

    def test_nonce_replay_binding_is_rejected(self):
        self.assertFalse(verify_confidential_attestation(self.record(), verifiers={"vendor-tee-v1": lambda _: True}, expected_nonce="other").verified)

    def test_concrete_registered_verifier_can_accept(self):
        self.assertTrue(verify_confidential_attestation(self.record(), verifiers={"vendor-tee-v1": lambda _: True}, expected_node_id="n1", expected_nonce="nonce").verified)

    def test_debug_enabled_is_rejected(self):
        record = self.record(); record["debug_disabled"] = False
        self.assertFalse(verify_confidential_attestation(record, verifiers={"vendor-tee-v1": lambda _: True}).verified)


if __name__ == "__main__":
    unittest.main()
