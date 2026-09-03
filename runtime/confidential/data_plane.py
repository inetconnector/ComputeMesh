"""Attestation-bound HTTPS data plane for opaque confidential envelopes.

The gateway forwards request ciphertext only.  Server identity is authenticated by
an exact TLS certificate SHA-256 fingerprint that must also be bound into the
verified attestation and the envelope AAD.  The protected endpoint returns only a
ConfidentialResponseEnvelope, so ordinary gateway code never handles prompt or
completion plaintext.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import http.client
import json
import ssl
from typing import Callable, Protocol
from urllib.parse import urlparse

from protocol.confidential_envelope import (
    ConfidentialEnvelope,
    ConfidentialResponseEnvelope,
)


MAX_DATA_PLANE_RESPONSE_BYTES = 8 * 1024 * 1024 + 256 * 1024


class ConfidentialDataPlaneError(RuntimeError):
    pass


@dataclass(frozen=True)
class AttestedConfidentialEndpoint:
    url: str
    node_id: str
    runtime_digest: str
    attestation_nonce: str
    recipient_public_key: str
    tls_certificate_sha256: str

    def validate(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ConfidentialDataPlaneError("confidential data plane must use an https URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfidentialDataPlaneError("confidential data-plane URL contains forbidden components")
        if not parsed.path or parsed.path == "/":
            raise ConfidentialDataPlaneError("confidential data-plane URL must contain an execution path")
        for name, value, limit in (
            ("node_id", self.node_id, 256),
            ("runtime_digest", self.runtime_digest, 512),
            ("attestation_nonce", self.attestation_nonce, 512),
            ("recipient_public_key", self.recipient_public_key, 1024),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ConfidentialDataPlaneError(f"invalid {name}")
        _validate_sha256(self.tls_certificate_sha256)

    def assert_matches(self, envelope: ConfidentialEnvelope) -> None:
        self.validate()
        envelope.validate()
        binding = envelope.binding
        if binding.node_id != self.node_id:
            raise ConfidentialDataPlaneError("confidential endpoint node binding mismatch")
        if binding.runtime_digest != self.runtime_digest:
            raise ConfidentialDataPlaneError("confidential endpoint runtime binding mismatch")
        if binding.attestation_nonce != self.attestation_nonce:
            raise ConfidentialDataPlaneError("confidential endpoint attestation binding mismatch")
        if binding.data_plane_tls_sha256 != self.tls_certificate_sha256:
            raise ConfidentialDataPlaneError("confidential endpoint TLS binding mismatch")


class ConfidentialDataPlane(Protocol):
    def execute(
        self,
        envelope: ConfidentialEnvelope,
        *,
        endpoint: AttestedConfidentialEndpoint,
    ) -> ConfidentialResponseEnvelope:
        """Forward one opaque protected request and return opaque protected output."""


ConnectionFactory = Callable[[str, int, ssl.SSLContext, float], http.client.HTTPSConnection]


def _default_connection_factory(
    host: str,
    port: int,
    context: ssl.SSLContext,
    timeout: float,
) -> http.client.HTTPSConnection:
    return http.client.HTTPSConnection(host, port=port, context=context, timeout=timeout)


class PinnedHttpsConfidentialDataPlane:
    """HTTPS transport with attestation-bound certificate pinning and strict framing."""

    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
        timeout_seconds: float = 120.0,
        max_response_bytes: int = MAX_DATA_PLANE_RESPONSE_BYTES,
        connection_factory: ConnectionFactory = _default_connection_factory,
    ) -> None:
        if not 0.1 <= timeout_seconds <= 600.0:
            raise ValueError("confidential data-plane timeout must be between 0.1 and 600 seconds")
        if not 1024 <= max_response_bytes <= 16 * 1024 * 1024:
            raise ValueError("invalid confidential data-plane response limit")
        context = ssl_context or ssl.create_default_context()
        # TLS 1.3 keeps the protected transport policy unambiguous. Deployments
        # using a private attested certificate may inject a context with a pinned
        # CA or CERT_NONE; the exact leaf fingerprint below remains mandatory.
        if context.minimum_version < ssl.TLSVersion.TLSv1_3:
            context.minimum_version = ssl.TLSVersion.TLSv1_3
        self.ssl_context = context
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.connection_factory = connection_factory

    def execute(
        self,
        envelope: ConfidentialEnvelope,
        *,
        endpoint: AttestedConfidentialEndpoint,
    ) -> ConfidentialResponseEnvelope:
        endpoint.assert_matches(envelope)
        parsed = urlparse(endpoint.url)
        host = parsed.hostname or ""
        port = parsed.port or 443
        path = parsed.path
        request_body = json.dumps(
            {
                "schema_version": 1,
                "confidential_protocol_version": envelope.schema_version,
                "envelope": envelope.to_dict(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        connection = self.connection_factory(host, port, self.ssl_context, self.timeout_seconds)
        try:
            connection.connect()
            sock = connection.sock
            if sock is None:
                raise ConfidentialDataPlaneError("confidential TLS socket was not established")
            peer_certificate = sock.getpeercert(binary_form=True)
            if not isinstance(peer_certificate, (bytes, bytearray)) or not peer_certificate:
                raise ConfidentialDataPlaneError("confidential endpoint did not present a certificate")
            actual_fingerprint = "sha256:" + hashlib.sha256(peer_certificate).hexdigest()
            if not hmac.compare_digest(actual_fingerprint, endpoint.tls_certificate_sha256):
                raise ConfidentialDataPlaneError("confidential endpoint certificate fingerprint mismatch")

            connection.request(
                "POST",
                path,
                body=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Connection": "close",
                    "X-ComputeMesh-Confidential-Protocol": str(envelope.schema_version),
                    "X-ComputeMesh-Job-ID": envelope.binding.job_id,
                    "X-ComputeMesh-Node-ID": envelope.binding.node_id,
                },
            )
            response = connection.getresponse()
            raw = response.read(self.max_response_bytes + 1)
            if len(raw) > self.max_response_bytes:
                raise ConfidentialDataPlaneError("confidential data-plane response exceeded size limit")
            if response.status != 200:
                raise ConfidentialDataPlaneError("confidential data-plane execution failed")
        except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
            raise ConfidentialDataPlaneError("confidential data-plane transport failed") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfidentialDataPlaneError("confidential data-plane returned malformed JSON") from exc
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "confidential_protocol_version",
            "response",
        }:
            raise ConfidentialDataPlaneError("confidential data-plane returned an invalid response contract")
        if value.get("schema_version") != 1 or value.get("confidential_protocol_version") != envelope.schema_version:
            raise ConfidentialDataPlaneError("confidential data-plane protocol version mismatch")
        response_value = value.get("response")
        if not isinstance(response_value, dict):
            raise ConfidentialDataPlaneError("confidential data-plane response envelope is missing")
        try:
            protected_response = ConfidentialResponseEnvelope.from_dict(response_value)
        except ValueError as exc:
            raise ConfidentialDataPlaneError("confidential data-plane response envelope is invalid") from exc
        if protected_response.request_envelope_id != envelope.envelope_id:
            raise ConfidentialDataPlaneError("confidential response is bound to another request")
        if protected_response.binding != envelope.binding:
            raise ConfidentialDataPlaneError("confidential response binding mismatch")
        return protected_response


def _validate_sha256(value: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        raise ConfidentialDataPlaneError("invalid confidential TLS certificate fingerprint")
    digest = value.removeprefix("sha256:")
    if any(ch not in "0123456789abcdef" for ch in digest):
        raise ConfidentialDataPlaneError("invalid confidential TLS certificate fingerprint")
