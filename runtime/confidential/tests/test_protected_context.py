from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from runtime.confidential.key_release import KeyReleaseBinding
from runtime.confidential.protected_context import (
    ProtectedContextError,
    ProtectedRequestContext,
    build_protected_execution_evidence,
)
from services.compliance.mesh_policy import ExecutionPrivacyClass


class ProtectedContextTests(unittest.TestCase):
    def setUp(self) -> None:
        now = datetime.now(UTC)
        self.tls_fingerprint = "sha256:" + "a" * 64
        self.context = ProtectedRequestContext(
            job_id="job-1",
            privacy_class=ExecutionPrivacyClass.CONFIDENTIAL,
            node_id="node-1",
            attestation_nonce="nonce-1",
            expected_runtime_digest="sha256:runtime",
            ciphertext_recipient_public_key="ephemeral-pub",
            data_plane_tls_sha256=self.tls_fingerprint,
        )
        self.attestation = {
            "schema_version": 1,
            "node_id": "node-1",
            "technology": "test-tee",
            "measurement": "measurement-1",
            "runtime_digest": "sha256:runtime",
            "ephemeral_public_key": "ephemeral-pub",
            "data_plane_tls_sha256": self.tls_fingerprint,
            "nonce": "nonce-1",
            "issued_at": (now - timedelta(seconds=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=1)).isoformat(),
            "debug_disabled": True,
        }
        self.release = KeyReleaseBinding(
            job_id="job-1",
            node_id="node-1",
            attestation_nonce="nonce-1",
            attested_ephemeral_public_key="ephemeral-pub",
        )

    def _build(self):
        return build_protected_execution_evidence(
            context=self.context,
            attestation=self.attestation,
            verifiers={"test-tee": lambda record: True},
            key_release=self.release,
            encrypted_data_plane=True,
            protected_memory=True,
            plaintext_logging_disabled=True,
            blinded_split_validated=True,
        )

    def test_complete_context_produces_bound_evidence(self) -> None:
        evidence = self._build()
        self.assertTrue(evidence.attestation_verified)
        self.assertTrue(evidence.runtime_measurement_bound)
        self.assertTrue(evidence.ephemeral_key_bound)
        self.assertTrue(evidence.content_key_release_bound)
        self.assertTrue(evidence.encrypted_data_plane)

    def test_runtime_digest_substitution_is_rejected(self) -> None:
        self.attestation["runtime_digest"] = "sha256:other"
        with self.assertRaisesRegex(ProtectedContextError, "runtime digest"):
            self._build()

    def test_ephemeral_key_substitution_is_rejected(self) -> None:
        self.attestation["ephemeral_public_key"] = "attacker-key"
        with self.assertRaisesRegex(ProtectedContextError, "recipient"):
            self._build()

    def test_data_plane_tls_substitution_is_rejected(self) -> None:
        self.attestation["data_plane_tls_sha256"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(ProtectedContextError, "TLS identity"):
            self._build()

    def test_missing_data_plane_tls_binding_is_rejected(self) -> None:
        self.attestation.pop("data_plane_tls_sha256")
        with self.assertRaisesRegex(ProtectedContextError, "TLS identity"):
            self._build()

    def test_key_release_cross_job_reuse_is_rejected(self) -> None:
        self.release = KeyReleaseBinding(
            job_id="job-2",
            node_id="node-1",
            attestation_nonce="nonce-1",
            attested_ephemeral_public_key="ephemeral-pub",
        )
        with self.assertRaisesRegex(ProtectedContextError, "key release"):
            self._build()

    def test_unregistered_tee_verifier_fails_closed(self) -> None:
        with self.assertRaisesRegex(ProtectedContextError, "not verified"):
            build_protected_execution_evidence(
                context=self.context,
                attestation=self.attestation,
                verifiers={},
                key_release=self.release,
                encrypted_data_plane=True,
                protected_memory=True,
                plaintext_logging_disabled=True,
                blinded_split_validated=True,
            )

    def test_public_context_is_forbidden(self) -> None:
        context = ProtectedRequestContext(
            job_id="job-1",
            privacy_class=ExecutionPrivacyClass.PUBLIC,
            node_id="node-1",
            attestation_nonce="nonce-1",
            expected_runtime_digest="sha256:runtime",
            ciphertext_recipient_public_key="ephemeral-pub",
            data_plane_tls_sha256=self.tls_fingerprint,
        )
        with self.assertRaisesRegex(ProtectedContextError, "cannot be PUBLIC"):
            build_protected_execution_evidence(
                context=context,
                attestation=self.attestation,
                verifiers={"test-tee": lambda record: True},
                key_release=self.release,
                encrypted_data_plane=True,
                protected_memory=True,
                plaintext_logging_disabled=True,
                blinded_split_validated=True,
            )


if __name__ == "__main__":
    unittest.main()
