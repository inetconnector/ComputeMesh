from __future__ import annotations

from http import HTTPStatus
import unittest

from runtime.confidential.execution_gate import ProtectedExecutionEvidence
from services.compliance.mesh_policy import ExecutionPrivacyClass
from services.gateway.live_handler import LiveGatewayHandler


class LiveConfidentialGateTests(unittest.TestCase):
    def _handler(self) -> tuple[LiveGatewayHandler, list[tuple[str, str, int]]]:
        handler = object.__new__(LiveGatewayHandler)
        errors: list[tuple[str, str, int]] = []
        handler._send_error_response = lambda message, kind, status: errors.append(  # type: ignore[method-assign]
            (message, kind, int(status))
        )
        handler.protected_execution_evidence_resolver = None
        return handler, errors

    @staticmethod
    def _ready(*, crypto: bool = False) -> ProtectedExecutionEvidence:
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
            crypto_private_validated=crypto,
        )

    def test_public_is_backward_compatible(self) -> None:
        handler, errors = self._handler()
        self.assertTrue(handler._enforce_protected_privacy({}))
        self.assertEqual(errors, [])

    def test_confidential_without_runtime_resolver_fails_closed(self) -> None:
        handler, errors = self._handler()
        self.assertFalse(
            handler._enforce_protected_privacy({"computemesh_privacy": "CONFIDENTIAL"})
        )
        self.assertEqual(errors[-1][1], "confidential_execution_unavailable")
        self.assertEqual(errors[-1][2], HTTPStatus.SERVICE_UNAVAILABLE)

    def test_confidential_complete_chain_is_admitted(self) -> None:
        handler, errors = self._handler()
        handler.protected_execution_evidence_resolver = lambda privacy, body: self._ready()
        self.assertTrue(
            handler._enforce_protected_privacy(
                {"computemesh_privacy": {"class": "confidential"}}
            )
        )
        self.assertEqual(errors, [])

    def test_missing_single_control_blocks_before_inference(self) -> None:
        handler, errors = self._handler()
        incomplete = self._ready()
        incomplete = ProtectedExecutionEvidence(
            **{**incomplete.__dict__, "content_key_release_bound": False}
        )
        handler.protected_execution_evidence_resolver = lambda privacy, body: incomplete
        self.assertFalse(
            handler._enforce_protected_privacy({"computemesh_privacy": "CONFIDENTIAL"})
        )
        self.assertIn("content_key_release_bound", errors[-1][0])

    def test_crypto_private_needs_crypto_private_validation(self) -> None:
        handler, errors = self._handler()
        handler.protected_execution_evidence_resolver = lambda privacy, body: self._ready()
        self.assertFalse(
            handler._enforce_protected_privacy({"computemesh_privacy": "CRYPTO_PRIVATE"})
        )
        self.assertIn("crypto_private_validated", errors[-1][0])

    def test_invalid_privacy_class_is_rejected(self) -> None:
        handler, errors = self._handler()
        self.assertFalse(
            handler._enforce_protected_privacy({"computemesh_privacy": "SECRET_MAGIC"})
        )
        self.assertEqual(errors[-1][1], "invalid_request_error")
        self.assertEqual(errors[-1][2], HTTPStatus.BAD_REQUEST)

    def test_parser_maps_public_confidential_crypto_private(self) -> None:
        self.assertIs(
            LiveGatewayHandler._requested_privacy_class({}),
            ExecutionPrivacyClass.PUBLIC,
        )
        self.assertIs(
            LiveGatewayHandler._requested_privacy_class({"computemesh_privacy": "confidential"}),
            ExecutionPrivacyClass.CONFIDENTIAL,
        )
        self.assertIs(
            LiveGatewayHandler._requested_privacy_class({"computemesh_privacy": "crypto_private"}),
            ExecutionPrivacyClass.CRYPTO_PRIVATE,
        )


if __name__ == "__main__":
    unittest.main()
