from __future__ import annotations

import unittest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    create_confidential_request,
    generate_attested_recipient_keypair,
)
from protocol.confidential_stream import (
    ConfidentialStreamError,
    decrypt_stream_event,
    encrypt_stream_event_in_attested_recipient,
    openai_sse_bytes,
)


class ConfidentialStreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key, self.public_key = generate_attested_recipient_keypair()
        self.binding = ConfidentialBinding(
            account_id="owner-1",
            job_id="job-1",
            node_id="node-1",
            attestation_nonce="nonce-1",
            runtime_digest="sha256:runtime",
            data_plane_tls_sha256="sha256:" + "a" * 64,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
        )
        self.request, self.context = create_confidential_request(
            b'{"model":"model-a","messages":[],"stream":true}',
            recipient_public_key=self.public_key,
            binding=self.binding,
        )

    def tearDown(self) -> None:
        self.context.close()

    @staticmethod
    def _chunk(content: str) -> dict:
        return {
            "id": "chatcmpl-stream-1",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "model-a",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }

    def test_encrypted_chunks_round_trip_to_openai_sse(self) -> None:
        encrypted = encrypt_stream_event_in_attested_recipient(
            self.request,
            sequence=0,
            done=False,
            chunk=self._chunk("secret"),
            recipient_private_key=self.private_key,
        )
        self.assertNotIn("secret", repr(encrypted.to_dict()))
        event = decrypt_stream_event(
            encrypted,
            client_context=self.context,
            expected_sequence=0,
        )
        self.assertFalse(event.done)
        self.assertEqual(event.chunk["choices"][0]["delta"]["content"], "secret")
        sse = openai_sse_bytes(event)
        self.assertTrue(sse.startswith(b"data: {"))
        self.assertTrue(sse.endswith(b"\n\n"))

    def test_final_frame_emits_done(self) -> None:
        encrypted = encrypt_stream_event_in_attested_recipient(
            self.request,
            sequence=3,
            done=True,
            chunk=None,
            recipient_private_key=self.private_key,
        )
        event = decrypt_stream_event(
            encrypted,
            client_context=self.context,
            expected_sequence=3,
        )
        self.assertTrue(event.done)
        self.assertEqual(openai_sse_bytes(event), b"data: [DONE]\n\n")

    def test_reordered_frame_is_rejected(self) -> None:
        encrypted = encrypt_stream_event_in_attested_recipient(
            self.request,
            sequence=2,
            done=False,
            chunk=self._chunk("x"),
            recipient_private_key=self.private_key,
        )
        with self.assertRaisesRegex(ConfidentialStreamError, "sequence mismatch"):
            decrypt_stream_event(
                encrypted,
                client_context=self.context,
                expected_sequence=1,
            )

    def test_final_frame_cannot_smuggle_chunk(self) -> None:
        with self.assertRaisesRegex(ConfidentialStreamError, "must not contain"):
            encrypt_stream_event_in_attested_recipient(
                self.request,
                sequence=0,
                done=True,
                chunk=self._chunk("x"),
                recipient_private_key=self.private_key,
            )

    def test_non_chunk_openai_object_is_rejected_before_encryption(self) -> None:
        bad = self._chunk("x")
        bad["object"] = "chat.completion"
        with self.assertRaisesRegex(ConfidentialStreamError, "chunk object"):
            encrypt_stream_event_in_attested_recipient(
                self.request,
                sequence=0,
                done=False,
                chunk=bad,
                recipient_private_key=self.private_key,
            )


if __name__ == "__main__":
    unittest.main()
