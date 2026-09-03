from __future__ import annotations

import hashlib
import json
import ssl
import unittest

from protocol.confidential_envelope import (
    ConfidentialBinding,
    ConfidentialResponseEnvelope,
    create_confidential_request,
    encrypt_response_in_attested_recipient,
    generate_attested_recipient_keypair,
)
from runtime.confidential.data_plane import (
    AttestedConfidentialEndpoint,
    ConfidentialDataPlaneError,
    PinnedHttpsConfidentialDataPlane,
)


class _FakeSocket:
    def __init__(self, certificate: bytes) -> None:
        self.certificate = certificate

    def getpeercert(self, binary_form=False):
        return self.certificate if binary_form else {}


class _FakeResponse:
    def __init__(self, *, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, amount: int) -> bytes:
        return self._body[:amount]


class _FakeConnection:
    def __init__(self, certificate: bytes, response_body: bytes, status: int = 200) -> None:
        self.sock = _FakeSocket(certificate)
        self.response = _FakeResponse(status=status, body=response_body)
        self.request_args = None
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def request(self, method, path, body=None, headers=None) -> None:
        self.request_args = (method, path, body, headers)

    def getresponse(self):
        return self.response

    def close(self) -> None:
        self.closed = True


class ConfidentialDataPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recipient_private, self.recipient_public = generate_attested_recipient_keypair()
        self.certificate = b"DER-CERTIFICATE-FOR-TEST"
        self.fingerprint = "sha256:" + hashlib.sha256(self.certificate).hexdigest()
        self.binding = ConfidentialBinding(
            account_id="acct-1",
            job_id="job-1",
            node_id="node-1",
            attestation_nonce="nonce-1",
            runtime_digest="sha256:runtime",
            data_plane_tls_sha256=self.fingerprint,
            privacy_class="CONFIDENTIAL",
            operation="chat_completion",
        )
        self.request, self.client_context = create_confidential_request(
            b"GATEWAY-MUST-NEVER-SEE-THIS-PROMPT",
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        self.protected_response = encrypt_response_in_attested_recipient(
            self.request,
            b"GATEWAY-MUST-NEVER-SEE-THIS-OUTPUT",
            recipient_private_key=self.recipient_private,
        )
        self.endpoint = AttestedConfidentialEndpoint(
            url="https://tee.example:8443/v1/confidential/execute",
            node_id="node-1",
            runtime_digest="sha256:runtime",
            attestation_nonce="nonce-1",
            recipient_public_key=self.recipient_public,
            tls_certificate_sha256=self.fingerprint,
        )

    def tearDown(self) -> None:
        self.client_context.close()

    def _body(self, response: ConfidentialResponseEnvelope | None = None) -> bytes:
        return json.dumps(
            {
                "schema_version": 1,
                "confidential_protocol_version": 2,
                "response": (response or self.protected_response).to_dict(),
            }
        ).encode("utf-8")

    def _plane(self, fake: _FakeConnection) -> PinnedHttpsConfidentialDataPlane:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return PinnedHttpsConfidentialDataPlane(
            ssl_context=context,
            connection_factory=lambda host, port, ctx, timeout: fake,
        )

    def test_forwards_only_opaque_envelope_and_returns_opaque_response(self) -> None:
        fake = _FakeConnection(self.certificate, self._body())
        result = self._plane(fake).execute(self.request, endpoint=self.endpoint)
        self.assertEqual(result, self.protected_response)
        self.assertTrue(fake.connected)
        self.assertTrue(fake.closed)
        method, path, body, headers = fake.request_args
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v1/confidential/execute")
        encoded = body.decode("utf-8")
        self.assertNotIn("GATEWAY-MUST-NEVER-SEE-THIS-PROMPT", encoded)
        self.assertNotIn("GATEWAY-MUST-NEVER-SEE-THIS-OUTPUT", encoded)
        self.assertIn(self.request.ciphertext, encoded)
        self.assertEqual(headers["X-ComputeMesh-Job-ID"], "job-1")

    def test_certificate_pin_mismatch_fails_closed_before_request(self) -> None:
        fake = _FakeConnection(b"ATTACKER-CERT", self._body())
        with self.assertRaisesRegex(ConfidentialDataPlaneError, "fingerprint mismatch"):
            self._plane(fake).execute(self.request, endpoint=self.endpoint)
        self.assertIsNone(fake.request_args)

    def test_endpoint_runtime_substitution_is_rejected_before_connect(self) -> None:
        endpoint = AttestedConfidentialEndpoint(
            **{**self.endpoint.__dict__, "runtime_digest": "sha256:attacker-runtime"}
        )
        fake = _FakeConnection(self.certificate, self._body())
        with self.assertRaisesRegex(ConfidentialDataPlaneError, "runtime binding mismatch"):
            self._plane(fake).execute(self.request, endpoint=endpoint)
        self.assertFalse(fake.connected)

    def test_endpoint_tls_binding_substitution_is_rejected_before_connect(self) -> None:
        endpoint = AttestedConfidentialEndpoint(
            **{**self.endpoint.__dict__, "tls_certificate_sha256": "sha256:" + "b" * 64}
        )
        fake = _FakeConnection(self.certificate, self._body())
        with self.assertRaisesRegex(ConfidentialDataPlaneError, "TLS binding mismatch"):
            self._plane(fake).execute(self.request, endpoint=endpoint)
        self.assertFalse(fake.connected)

    def test_response_for_other_request_is_rejected(self) -> None:
        other_request, other_context = create_confidential_request(
            b"other",
            recipient_public_key=self.recipient_public,
            binding=self.binding,
        )
        try:
            other_response = encrypt_response_in_attested_recipient(
                other_request,
                b"other response",
                recipient_private_key=self.recipient_private,
            )
            fake = _FakeConnection(self.certificate, self._body(other_response))
            with self.assertRaisesRegex(ConfidentialDataPlaneError, "another request"):
                self._plane(fake).execute(self.request, endpoint=self.endpoint)
        finally:
            other_context.close()

    def test_non_https_endpoint_is_rejected(self) -> None:
        endpoint = AttestedConfidentialEndpoint(
            **{**self.endpoint.__dict__, "url": "http://tee.example/v1/confidential/execute"}
        )
        fake = _FakeConnection(self.certificate, self._body())
        with self.assertRaisesRegex(ConfidentialDataPlaneError, "https"):
            self._plane(fake).execute(self.request, endpoint=endpoint)
        self.assertFalse(fake.connected)

    def test_error_status_does_not_forward_error_body_to_caller(self) -> None:
        fake = _FakeConnection(self.certificate, b'{"secret_error":"internal"}', status=500)
        with self.assertRaisesRegex(ConfidentialDataPlaneError, "execution failed"):
            self._plane(fake).execute(self.request, endpoint=self.endpoint)


if __name__ == "__main__":
    unittest.main()
