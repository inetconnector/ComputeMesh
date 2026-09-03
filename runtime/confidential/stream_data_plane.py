"""TLS-pinned streaming data plane for opaque protected OpenAI chunks.

The gateway validates only encrypted envelope metadata and the final content-free
usage receipt.  It never decrypts OpenAI stream chunks.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import http.client
import json
import ssl
from typing import Iterator
from urllib.parse import urlparse

from protocol.confidential_envelope import ConfidentialEnvelope, ConfidentialResponseEnvelope
from protocol.confidential_metering import ConfidentialUsageReceipt
from runtime.confidential.data_plane import (
    AttestedConfidentialEndpoint,
    ConfidentialDataPlaneError,
    ConnectionFactory,
    _default_connection_factory,
)


MAX_STREAM_LINE_BYTES = 2 * 1024 * 1024
MAX_STREAM_EVENTS = 10_000_001


@dataclass(frozen=True)
class ConfidentialStreamDataPlaneEvent:
    response: ConfidentialResponseEnvelope
    done: bool
    usage_receipt: ConfidentialUsageReceipt | None = None


class PinnedHttpsConfidentialStreamDataPlane:
    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
        timeout_seconds: float = 120.0,
        connection_factory: ConnectionFactory = _default_connection_factory,
    ) -> None:
        if not 0.1 <= timeout_seconds <= 600.0:
            raise ValueError("confidential stream timeout must be between 0.1 and 600 seconds")
        context = ssl_context or ssl.create_default_context()
        if context.minimum_version < ssl.TLSVersion.TLSv1_3:
            context.minimum_version = ssl.TLSVersion.TLSv1_3
        self.ssl_context = context
        self.timeout_seconds = timeout_seconds
        self.connection_factory = connection_factory

    def stream_execute(
        self,
        envelope: ConfidentialEnvelope,
        *,
        endpoint: AttestedConfidentialEndpoint,
    ) -> Iterator[ConfidentialStreamDataPlaneEvent]:
        endpoint.assert_matches(envelope)
        parsed = urlparse(endpoint.url)
        host = parsed.hostname or ""
        port = parsed.port or 443
        request_body = json.dumps(
            {
                "schema_version": 1,
                "confidential_protocol_version": envelope.schema_version,
                "stream": True,
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
                parsed.path,
                body=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/x-ndjson",
                    "Connection": "close",
                    "X-ComputeMesh-Confidential-Protocol": str(envelope.schema_version),
                    "X-ComputeMesh-Confidential-Stream": "1",
                    "X-ComputeMesh-Job-ID": envelope.binding.job_id,
                    "X-ComputeMesh-Node-ID": envelope.binding.node_id,
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise ConfidentialDataPlaneError("confidential streaming execution failed")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/x-ndjson":
                raise ConfidentialDataPlaneError("confidential stream returned invalid content type")

            seen = 0
            done_seen = False
            while True:
                line = response.readline(MAX_STREAM_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_STREAM_LINE_BYTES:
                    raise ConfidentialDataPlaneError("confidential stream frame exceeds size limit")
                if not line.strip():
                    continue
                seen += 1
                if seen > MAX_STREAM_EVENTS:
                    raise ConfidentialDataPlaneError("confidential stream exceeds event limit")
                event = self._parse_event(line, envelope=envelope)
                if done_seen:
                    raise ConfidentialDataPlaneError("confidential stream contained data after final frame")
                if event.done:
                    done_seen = True
                yield event
            if not done_seen:
                raise ConfidentialDataPlaneError("confidential stream ended without final metering frame")
        except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
            raise ConfidentialDataPlaneError("confidential streaming transport failed") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

    @staticmethod
    def _parse_event(
        raw: bytes,
        *,
        envelope: ConfidentialEnvelope,
    ) -> ConfidentialStreamDataPlaneEvent:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfidentialDataPlaneError("confidential stream returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise ConfidentialDataPlaneError("confidential stream event must be an object")
        event_type = value.get("type")
        common = {"schema_version", "confidential_protocol_version", "type", "response"}
        if event_type == "chunk":
            if set(value) != common:
                raise ConfidentialDataPlaneError("invalid confidential stream chunk contract")
        elif event_type == "done":
            if set(value) != common | {"usage_receipt"}:
                raise ConfidentialDataPlaneError("invalid confidential stream final contract")
        else:
            raise ConfidentialDataPlaneError("invalid confidential stream event type")
        if value.get("schema_version") != 1 or value.get("confidential_protocol_version") != envelope.schema_version:
            raise ConfidentialDataPlaneError("confidential stream protocol version mismatch")
        response_value = value.get("response")
        if not isinstance(response_value, dict):
            raise ConfidentialDataPlaneError("confidential stream response envelope is missing")
        try:
            protected_response = ConfidentialResponseEnvelope.from_dict(response_value)
        except ValueError as exc:
            raise ConfidentialDataPlaneError("confidential stream response envelope is invalid") from exc
        if protected_response.request_envelope_id != envelope.envelope_id:
            raise ConfidentialDataPlaneError("confidential stream response is bound to another request")
        if protected_response.binding != envelope.binding:
            raise ConfidentialDataPlaneError("confidential stream response binding mismatch")
        if event_type == "chunk":
            return ConfidentialStreamDataPlaneEvent(response=protected_response, done=False)
        receipt_value = value.get("usage_receipt")
        if not isinstance(receipt_value, dict):
            raise ConfidentialDataPlaneError("confidential stream final usage receipt is missing")
        try:
            receipt = ConfidentialUsageReceipt.from_dict(receipt_value)
        except ValueError as exc:
            raise ConfidentialDataPlaneError("confidential stream usage receipt is invalid") from exc
        if receipt.request_envelope_id != envelope.envelope_id:
            raise ConfidentialDataPlaneError("confidential stream usage receipt request mismatch")
        if receipt.response_id != protected_response.response_id:
            raise ConfidentialDataPlaneError("confidential stream usage receipt final-response mismatch")
        return ConfidentialStreamDataPlaneEvent(
            response=protected_response,
            done=True,
            usage_receipt=receipt,
        )
