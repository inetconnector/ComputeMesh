from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

from protocol.confidential_metering import (
    ConfidentialMeteringError,
    ConfidentialUsageReceipt,
    generate_attested_metering_keypair,
    sign_confidential_usage,
    verify_confidential_usage_receipt,
)


class ConfidentialMeteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key, self.public_key = generate_attested_metering_keypair()
        self.finished = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
        self.receipt = sign_confidential_usage(
            private_key=self.private_key,
            account_id="acct-1",
            job_id="job-1",
            request_envelope_id="a" * 32,
            response_id="b" * 32,
            node_id="node-1",
            runtime_digest="sha256:runtime",
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
            model_id="qwen/qwen2.5-7b-instruct",
            prompt_tokens=123,
            completion_tokens=45,
            finished_at=self.finished,
        )

    def _verify(self, receipt=None, public_key=None):
        return verify_confidential_usage_receipt(
            receipt or self.receipt,
            attested_metering_public_key=public_key or self.public_key,
            expected_account_id="acct-1",
            expected_job_id="job-1",
            expected_request_envelope_id="a" * 32,
            expected_response_id="b" * 32,
            expected_node_id="node-1",
            expected_runtime_digest="sha256:runtime",
            expected_privacy_class="CONFIDENTIAL",
            expected_operation="chat_completion",
            expected_model_id="qwen/qwen2.5-7b-instruct",
            max_prompt_tokens=1000,
            max_completion_tokens=100,
            not_after=self.finished + timedelta(minutes=5),
        )

    def test_valid_receipt_verifies_without_content(self) -> None:
        verified = self._verify()
        self.assertEqual(verified.prompt_tokens, 123)
        encoded = repr(verified.to_dict())
        self.assertNotIn("prompt", encoded.lower().replace("prompt_tokens", ""))
        self.assertNotIn("assistant", encoded.lower())

    def test_signature_tampering_is_rejected(self) -> None:
        value = self.receipt.to_dict()
        value["completion_tokens"] = 46
        tampered = ConfidentialUsageReceipt.from_dict(value)
        with self.assertRaisesRegex(ConfidentialMeteringError, "signature"):
            self._verify(tampered)

    def test_wrong_attested_metering_key_is_rejected(self) -> None:
        _, wrong_public = generate_attested_metering_keypair()
        with self.assertRaisesRegex(ConfidentialMeteringError, "signature"):
            self._verify(public_key=wrong_public)

    def test_cross_job_and_cross_response_reuse_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfidentialMeteringError, "job_id"):
            verify_confidential_usage_receipt(
                self.receipt,
                attested_metering_public_key=self.public_key,
                expected_account_id="acct-1",
                expected_job_id="job-2",
                expected_request_envelope_id="a" * 32,
                expected_response_id="b" * 32,
                expected_node_id="node-1",
                expected_runtime_digest="sha256:runtime",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
                expected_model_id="qwen/qwen2.5-7b-instruct",
                max_prompt_tokens=1000,
                max_completion_tokens=100,
            )
        with self.assertRaisesRegex(ConfidentialMeteringError, "response_id"):
            verify_confidential_usage_receipt(
                self.receipt,
                attested_metering_public_key=self.public_key,
                expected_account_id="acct-1",
                expected_job_id="job-1",
                expected_request_envelope_id="a" * 32,
                expected_response_id="c" * 32,
                expected_node_id="node-1",
                expected_runtime_digest="sha256:runtime",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
                expected_model_id="qwen/qwen2.5-7b-instruct",
                max_prompt_tokens=1000,
                max_completion_tokens=100,
            )

    def test_declared_token_limits_are_enforced(self) -> None:
        with self.assertRaisesRegex(ConfidentialMeteringError, "prompt token"):
            verify_confidential_usage_receipt(
                self.receipt,
                attested_metering_public_key=self.public_key,
                expected_account_id="acct-1",
                expected_job_id="job-1",
                expected_request_envelope_id="a" * 32,
                expected_response_id="b" * 32,
                expected_node_id="node-1",
                expected_runtime_digest="sha256:runtime",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
                expected_model_id="qwen/qwen2.5-7b-instruct",
                max_prompt_tokens=100,
                max_completion_tokens=100,
            )
        with self.assertRaisesRegex(ConfidentialMeteringError, "completion token"):
            verify_confidential_usage_receipt(
                self.receipt,
                attested_metering_public_key=self.public_key,
                expected_account_id="acct-1",
                expected_job_id="job-1",
                expected_request_envelope_id="a" * 32,
                expected_response_id="b" * 32,
                expected_node_id="node-1",
                expected_runtime_digest="sha256:runtime",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
                expected_model_id="qwen/qwen2.5-7b-instruct",
                max_prompt_tokens=1000,
                max_completion_tokens=10,
            )

    def test_receipt_after_session_expiry_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfidentialMeteringError, "session lifetime"):
            verify_confidential_usage_receipt(
                self.receipt,
                attested_metering_public_key=self.public_key,
                expected_account_id="acct-1",
                expected_job_id="job-1",
                expected_request_envelope_id="a" * 32,
                expected_response_id="b" * 32,
                expected_node_id="node-1",
                expected_runtime_digest="sha256:runtime",
                expected_privacy_class="CONFIDENTIAL",
                expected_operation="chat_completion",
                expected_model_id="qwen/qwen2.5-7b-instruct",
                max_prompt_tokens=1000,
                max_completion_tokens=100,
                not_after=self.finished - timedelta(seconds=1),
            )

    def test_unknown_fields_are_rejected(self) -> None:
        value = self.receipt.to_dict()
        value["prompt_text"] = "forbidden"
        with self.assertRaisesRegex(ConfidentialMeteringError, "contract"):
            ConfidentialUsageReceipt.from_dict(value)


if __name__ == "__main__":
    unittest.main()
