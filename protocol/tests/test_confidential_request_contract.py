from __future__ import annotations

import unittest

from protocol.confidential_request_contract import (
    ConfidentialRequestContractError,
    create_committed_attestation_nonce,
    request_contract_sha256,
    verify_committed_attestation_nonce,
)


class ConfidentialRequestContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = {
            "model_id": "qwen/qwen2.5-7b-instruct",
            "max_prompt_tokens": 4096,
            "max_completion_tokens": 512,
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
