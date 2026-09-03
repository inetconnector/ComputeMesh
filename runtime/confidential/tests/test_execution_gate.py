from __future__ import annotations

import unittest

from runtime.confidential.execution_gate import (
    ProtectedExecutionEvidence,
    ProtectedExecutionUnavailable,
    evaluate_protected_execution,
    require_protected_execution,
)
from services.compliance.mesh_policy import ExecutionPrivacyClass


class ProtectedExecutionGateTests(unittest.TestCase):
    def _confidential_ready(self) -> ProtectedExecutionEvidence:
        return ProtectedExecutionEvidence(
            attestation_verified=True,
            attestation_fresh=True,
            debug_disabled=True,
            runtime_measurement_bound=True,
            ephemeral_key_bound=True,
            content_key_release_bound=True,
            encrypted_data_plane=True,
            protected_memory=True,
            plaintext_logging_disabled=True,
            blinded_split_validated=True,
        )

    def test_public_does_not_claim_confidential_controls(self) -> None:
        decision = evaluate_protected_execution(
            ExecutionPrivacyClass.PUBLIC,
            ProtectedExecutionEvidence(),
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.missing, ())

    def test_confidential_fails_when_any_control_is_missing(self) -> None:
        evidence = self._confidential_ready()
        evidence = ProtectedExecutionEvidence(
            **{**evidence.__dict__, "encrypted_data_plane": False}
        )
        decision = evaluate_protected_execution(ExecutionPrivacyClass.CONFIDENTIAL, evidence)
        self.assertFalse(decision.allowed)
        self.assertIn("encrypted_data_plane", decision.missing)
        with self.assertRaises(ProtectedExecutionUnavailable):
            require_protected_execution(ExecutionPrivacyClass.CONFIDENTIAL, evidence)

    def test_confidential_requires_validated_blinded_split(self) -> None:
        evidence = self._confidential_ready()
        evidence = ProtectedExecutionEvidence(
            **{**evidence.__dict__, "blinded_split_validated": False}
        )
        decision = evaluate_protected_execution(ExecutionPrivacyClass.CONFIDENTIAL, evidence)
        self.assertFalse(decision.allowed)
        self.assertIn("blinded_split_validated", decision.missing)

    def test_confidential_passes_only_complete_chain(self) -> None:
        decision = require_protected_execution(
            ExecutionPrivacyClass.CONFIDENTIAL,
            self._confidential_ready(),
        )
        self.assertTrue(decision.allowed)

    def test_crypto_private_additionally_requires_crypto_validation(self) -> None:
        evidence = self._confidential_ready()
        decision = evaluate_protected_execution(ExecutionPrivacyClass.CRYPTO_PRIVATE, evidence)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.missing, ("crypto_private_validated",))

        ready = ProtectedExecutionEvidence(
            **{**evidence.__dict__, "crypto_private_validated": True}
        )
        self.assertTrue(
            require_protected_execution(
                ExecutionPrivacyClass.CRYPTO_PRIVATE,
                ready,
            ).allowed
        )


if __name__ == "__main__":
    unittest.main()
