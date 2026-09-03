from __future__ import annotations

import unittest

from protocol.confidential_request_contract import (
    ConfidentialRequestContractError,
    create_committed_attestation_nonce,
    create_committed_session_attestation_nonce,
    request_contract_sha256,
    verify_committed_attestation_nonce,
    verify_committed_session_attestation_nonce,
)


class ConfidentialRequestContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = {
            "model_id": "qwen/qwen2.5-7b-instruct",
            "max_prompt_tokens": 4096,
            "max_completion_tokens": 512,
        }
        self.session_values = {
            **self.values,
            "account_id": "owner-1",
            "job_id": "job-1",
            "node_id": "node-1",
            "runtime_digest": "sha256:runtime",
            "recipient_public_key": "recipient-key",
            "metering_public_key": "metering-key",
            "data_plane_tls_sha256": "sha256:" + "a" * 64,
            "privacy_class": "CONFIDENTIAL",
            "operation": "chat_completion",
        }

    def test_digest_is_deterministic(self) -> None:
        first = request_contract_sha256(**self.values)
        second = request_contract_sha256(
            max_completion_tokens=512,
            model_id="qwen/qwen2.5-7b-instruct",
            max_prompt_tokens=4096,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_correct_committed_nonce_verifies(self) -> None:
        nonce = create_committed_attestation_nonce(**self.values, entropy=b"a" * 32)
        verify_committed_attestation_nonce(nonce, **self.values)

    def test_model_substitution_fails(self) -> None:
        nonce = create_committed_attestation_nonce(**self.values, entropy=b"b" * 32)
        with self.assertRaisesRegex(ConfidentialRequestContractError, "contract mismatch"):
            verify_committed_attestation_nonce(nonce, **{**self.values, "model_id": "other/model"})

    def test_prompt_limit_substitution_fails(self) -> None:
        nonce = create_committed_attestation_nonce(**self.values, entropy=b"c" * 32)
        with self.assertRaisesRegex(ConfidentialRequestContractError, "contract mismatch"):
            verify_committed_attestation_nonce(
                nonce,
                **{**self.values, "max_prompt_tokens": 4097},
            )

    def test_completion_limit_substitution_fails(self) -> None:
        nonce = create_committed_attestation_nonce(**self.values, entropy=b"d" * 32)
        with self.assertRaisesRegex(ConfidentialRequestContractError, "contract mismatch"):
            verify_committed_attestation_nonce(
                nonce,
                **{**self.values, "max_completion_tokens": 513},
            )

    def test_cmrc2_is_compatible_with_request_only_verification(self) -> None:
        nonce = create_committed_session_attestation_nonce(
            **self.session_values,
            entropy=b"e" * 32,
        )
        verify_committed_attestation_nonce(nonce, **self.values)

    def test_cmrc2_full_session_verifies_with_broker_challenge(self) -> None:
        entropy = b"f" * 32
        nonce = create_committed_session_attestation_nonce(
            **self.session_values,
            entropy=entropy,
        )
        verify_committed_session_attestation_nonce(
            nonce,
            **self.session_values,
            expected_entropy=entropy,
        )

    def test_cmrc2_recipient_key_substitution_fails(self) -> None:
        nonce = create_committed_session_attestation_nonce(
            **self.session_values,
            entropy=b"g" * 32,
        )
        with self.assertRaisesRegex(ConfidentialRequestContractError, "session contract mismatch"):
            verify_committed_session_attestation_nonce(
                nonce,
                **{**self.session_values, "recipient_public_key": "other-key"},
            )

    def test_cmrc2_broker_challenge_substitution_fails(self) -> None:
        nonce = create_committed_session_attestation_nonce(
            **self.session_values,
            entropy=b"h" * 32,
        )
        with self.assertRaisesRegex(ConfidentialRequestContractError, "freshness challenge mismatch"):
            verify_committed_session_attestation_nonce(
                nonce,
                **self.session_values,
                expected_entropy=b"i" * 32,
            )

    def test_malformed_nonce_fails_closed(self) -> None:
        bad_values = (
            "nonce-123",
            "cmrc1:not-a-digest:" + "aa" * 32,
            "cmrc1:" + "0" * 64 + ":zz",
            "cmrc1:" + "0" * 64 + ":aa",
        )
        for nonce in bad_values:
            with self.subTest(nonce=nonce):
                with self.assertRaises(ConfidentialRequestContractError):
                    verify_committed_attestation_nonce(nonce, **self.values)

    def test_creation_rejects_low_entropy(self) -> None:
        with self.assertRaisesRegex(ConfidentialRequestContractError, "entropy"):
            create_committed_attestation_nonce(**self.values, entropy=b"short")


if __name__ == "__main__":
    unittest.main()
