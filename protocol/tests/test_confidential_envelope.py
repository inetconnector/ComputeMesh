from __future__ import annotations

import copy
import unittest

from protocol.confidential_envelope import (
    SCHEMA_VERSION,
    ConfidentialBinding,
    ConfidentialEnvelope,
    ConfidentialEnvelopeError,
    ConfidentialResponseEnvelope,
    create_confidential_request,
    decrypt_confidential_response,
    decrypt_in_attested_recipient,
    encrypt_for_attested_recipient,
    encrypt_response_in_attested_recipient,
    generate_attested_recipient_keypair,
)
from services.common.secure_memory import secure_zero_memory


class ConfidentialEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recipient_private, self.recipient_public = generate_attested_recipient_keypair()
        self.binding = ConfidentialBinding(
            account_id="acct-123",
            job_id="job-123",
            node_id="node-abc",
            attestation_nonce="att-nonce-1",
            runtime_digest="sha256:approved-runtime",
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
        )

    def _encrypted(self, plaintext: bytes = b'{"messages":[{"role":"user","content":"secret"}]}'):
        return encrypt_for_attested_recipient(
            plaintext,
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )

    def test_round_trip_returns_mutable_zeroizable_plaintext(self) -> None:
        envelope = self._encrypted(b"highly confidential prompt")
        plaintext = decrypt_in_attested_recipient(
            envelope,
            recipient_private_key=self.recipient_private,
            expected_binding=self.binding,
        )
        self.assertIsInstance(plaintext, bytearray)
        self.assertEqual(plaintext, b"highly confidential prompt")
        secure_zero_memory(plaintext)
        self.assertEqual(plaintext, bytearray(len(plaintext)))

    def test_bidirectional_round_trip_keeps_gateway_content_opaque(self) -> None:
        request, client_context = create_confidential_request(
            b"TOP-SECRET-REQUEST",
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        try:
            request_plaintext = decrypt_in_attested_recipient(
                request,
                recipient_private_key=self.recipient_private,
                expected_binding=self.binding,
            )
            try:
                self.assertEqual(request_plaintext, b"TOP-SECRET-REQUEST")
            finally:
                secure_zero_memory(request_plaintext)

            response = encrypt_response_in_attested_recipient(
                request,
                b"TOP-SECRET-RESPONSE",
                recipient_private_key=self.recipient_private,
            )
            gateway_view = repr({"request": request.to_dict(), "response": response.to_dict()})
            self.assertNotIn("TOP-SECRET-REQUEST", gateway_view)
            self.assertNotIn("TOP-SECRET-RESPONSE", gateway_view)
            response_plaintext = decrypt_confidential_response(
                response,
                client_context=client_context,
            )
            try:
                self.assertEqual(response_plaintext, b"TOP-SECRET-RESPONSE")
            finally:
                secure_zero_memory(response_plaintext)
        finally:
            client_context.close()

    def test_client_context_is_single_lifetime_and_zeroizable(self) -> None:
        request, context = create_confidential_request(
            b"request",
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        response = encrypt_response_in_attested_recipient(
            request,
            b"response",
            recipient_private_key=self.recipient_private,
        )
        context.close()
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "closed"):
            decrypt_confidential_response(response, client_context=context)

    def test_gateway_safe_dict_contains_no_plaintext(self) -> None:
        envelope = self._encrypted(b"NEVER-APPEAR-IN-ROUTER")
        encoded = repr(envelope.to_dict())
        self.assertNotIn("NEVER-APPEAR-IN-ROUTER", encoded)

    def _binding_with(self, **overrides) -> ConfidentialBinding:
        values = self.binding.as_dict()
        values.update(overrides)
        return ConfidentialBinding(**values)

    def test_wrong_job_binding_is_rejected_before_decrypt(self) -> None:
        envelope = self._encrypted()
        wrong = self._binding_with(job_id="job-other")
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "binding mismatch"):
            decrypt_in_attested_recipient(
                envelope,
                recipient_private_key=self.recipient_private,
                expected_binding=wrong,
            )

    def test_account_binding_is_authenticated(self) -> None:
        value = self._encrypted().to_dict()
        value["binding"]["account_id"] = "acct-attacker"
        parsed = ConfidentialEnvelope.from_dict(value)
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "binding mismatch"):
            decrypt_in_attested_recipient(
                parsed,
                recipient_private_key=self.recipient_private,
                expected_binding=self.binding,
            )

    def test_privacy_class_binding_is_authenticated(self) -> None:
        envelope = self._encrypted()
        wrong = self._binding_with(privacy_class="CRYPTO_PRIVATE")
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "binding mismatch"):
            decrypt_in_attested_recipient(
                envelope,
                recipient_private_key=self.recipient_private,
                expected_binding=wrong,
            )

    def test_operation_binding_is_authenticated(self) -> None:
        envelope = self._encrypted()
        wrong = self._binding_with(operation="ollama_chat")
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "binding mismatch"):
            decrypt_in_attested_recipient(
                envelope,
                recipient_private_key=self.recipient_private,
                expected_binding=wrong,
            )

    def test_wrong_recipient_key_cannot_decrypt(self) -> None:
        envelope = self._encrypted()
        wrong_private, _ = generate_attested_recipient_keypair()
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "authentication failed"):
            decrypt_in_attested_recipient(
                envelope,
                recipient_private_key=wrong_private,
                expected_binding=self.binding,
            )

    def test_ciphertext_tampering_is_rejected(self) -> None:
        value = self._encrypted().to_dict()
        tampered = copy.deepcopy(value)
        ciphertext = tampered["ciphertext"]
        replacement = "A" if ciphertext[-1] != "A" else "B"
        tampered["ciphertext"] = ciphertext[:-1] + replacement
        with self.assertRaises(ConfidentialEnvelopeError):
            decrypt_in_attested_recipient(
                tampered,
                recipient_private_key=self.recipient_private,
                expected_binding=self.binding,
            )

    def test_response_tampering_is_rejected(self) -> None:
        request, context = create_confidential_request(
            b"request",
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        try:
            response = encrypt_response_in_attested_recipient(
                request,
                b"response",
                recipient_private_key=self.recipient_private,
            ).to_dict()
            response["binding"]["runtime_digest"] = "sha256:attacker"
            parsed = ConfidentialResponseEnvelope.from_dict(response)
            with self.assertRaisesRegex(ConfidentialEnvelopeError, "binding mismatch"):
                decrypt_confidential_response(parsed, client_context=context)
        finally:
            context.close()

    def test_response_from_other_request_is_rejected(self) -> None:
        request_one, context_one = create_confidential_request(
            b"one",
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        request_two, context_two = create_confidential_request(
            b"two",
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        try:
            response_two = encrypt_response_in_attested_recipient(
                request_two,
                b"two-response",
                recipient_private_key=self.recipient_private,
            )
            with self.assertRaisesRegex(ConfidentialEnvelopeError, "request binding mismatch"):
                decrypt_confidential_response(response_two, client_context=context_one)
        finally:
            context_one.close()
            context_two.close()

    def test_unknown_fields_are_rejected(self) -> None:
        value = self._encrypted().to_dict()
        value["plaintext"] = "smuggled"
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "unexpected"):
            ConfidentialEnvelope.from_dict(value)

    def test_malformed_sender_key_is_rejected(self) -> None:
        value = self._encrypted().to_dict()
        value["sender_ephemeral_public_key"] = "AA"
        with self.assertRaises(ConfidentialEnvelopeError):
            ConfidentialEnvelope.from_dict(value)

    def test_legacy_v1_is_rejected_fail_closed(self) -> None:
        value = self._encrypted().to_dict()
        value["schema_version"] = 1
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "unsupported"):
            ConfidentialEnvelope.from_dict(value)
        self.assertEqual(SCHEMA_VERSION, 2)

    def test_invalid_public_privacy_class_is_rejected(self) -> None:
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "privacy_class"):
            self._binding_with(privacy_class="PUBLIC").validate()


if __name__ == "__main__":
    unittest.main()
