from __future__ import annotations

import copy
import unittest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    ConfidentialEnvelope,
    ConfidentialEnvelopeError,
    decrypt_in_attested_recipient,
    encrypt_for_attested_recipient,
    generate_attested_recipient_keypair,
)
from services.common.secure_memory import secure_zero_memory


class ConfidentialEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recipient_private, self.recipient_public = generate_attested_recipient_keypair()
        self.binding = ConfidentialBinding(
            job_id="job-123",
            node_id="node-abc",
            attestation_nonce="att-nonce-1",
            runtime_digest="sha256:approved-runtime",
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

    def test_gateway_safe_dict_contains_no_plaintext(self) -> None:
        envelope = self._encrypted(b"NEVER-APPEAR-IN-ROUTER")
        encoded = repr(envelope.to_dict())
        self.assertNotIn("NEVER-APPEAR-IN-ROUTER", encoded)

    def test_wrong_job_binding_is_rejected_before_decrypt(self) -> None:
        envelope = self._encrypted()
        wrong = ConfidentialBinding(
            job_id="job-other",
            node_id=self.binding.node_id,
            attestation_nonce=self.binding.attestation_nonce,
            runtime_digest=self.binding.runtime_digest,
        )
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

    def test_binding_tampering_changes_authenticated_context(self) -> None:
        value = self._encrypted().to_dict()
        value["binding"]["runtime_digest"] = "sha256:attacker-runtime"
        parsed = ConfidentialEnvelope.from_dict(value)
        with self.assertRaisesRegex(ConfidentialEnvelopeError, "binding mismatch"):
            decrypt_in_attested_recipient(
                parsed,
                recipient_private_key=self.recipient_private,
                expected_binding=self.binding,
            )

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


if __name__ == "__main__":
    unittest.main()
