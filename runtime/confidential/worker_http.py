"""TLS 1.3 HTTP data plane for the attested protected worker.

The service receives only encrypted ComputeMesh envelopes from the gateway. Request
plaintext exists only after `ProtectedWorkerSessionManager` has checked session
bindings and replay state. Access logging is disabled and responses are no-store.
"""
from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import threading
from typing import Any, Mapping
from urllib.parse import urlparse

from protocol.confidential_envelope import ConfidentialEnvelope, ConfidentialEnvelopeError, SCHEMA_VERSION
from runtime.confidential.protected_worker import ProtectedWorkerError, ProtectedWorkerSessionManager


MAX_WORKER_REQUEST_BYTES = 8 * 1024 * 1024 + 512 * 1024


class ProtectedWorkerHttpError(RuntimeError):
    pass


class ProtectedWorkerHttpService:
    def __init__(
        self,
        *,
        manager: ProtectedWorkerSessionManager,
        bind_host: str,
        bind_port: int,
        cert_file: Path | str,
        key_file: Path | str,
        execution_path: str,
    ) -> None:
        if not isinstance(bind_host, str) or not bind_host:
            raise ValueError("protected worker bind host is invalid")
        if not isinstance(bind_port, int) or isinstance(bind_port, bool) or not 0 <= bind_port <= 65535:
            raise ValueError("protected worker port is invalid")
        parsed = urlparse(execution_path)
        if not execution_path.startswith("/") or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("protected worker execution path is invalid")
        cert = Path(cert_file)
        key = Path(key_file)
        if cert.is_symlink() or key.is_symlink() or not cert.is_file() or not key.is_file():
            raise ValueError("protected worker TLS files must be regular non-symlink files")
        self.manager = manager
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.execution_path = execution_path
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_3
        self._context.maximum_version = ssl.TLSVersion.TLSv1_3
        self._context.load_cert_chain(certfile=str(cert), keyfile=str(key))
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def bound_port(self) -> int:
        return self.bind_port if self._httpd is None else int(self._httpd.server_address[1])

    def start(self) -> None:
        if self._httpd is not None:
            raise RuntimeError("protected worker HTTP service already started")
        manager = self.manager
        execution_path = self.execution_path

        class Handler(BaseHTTPRequestHandler):
            server_version = "ComputeMesh-ProtectedWorker/1"

            def do_POST(self) -> None:
                if self.path != execution_path:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                try:
                    value = self._read_body()
                    stream, envelope = self._parse_contract(value)
                    self._check_headers(envelope)
                    if stream:
                        self._stream(envelope)
                    else:
                        self._complete(envelope)
                except (ProtectedWorkerError, ConfidentialEnvelopeError, ValueError, TypeError):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "protected_execution_rejected"})

            def _read_body(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ProtectedWorkerHttpError("invalid content length") from exc
                if not 1 <= length <= MAX_WORKER_REQUEST_BYTES:
                    raise ProtectedWorkerHttpError("invalid protected worker request size")
                try:
                    value = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ProtectedWorkerHttpError("protected worker request is not JSON") from exc
                if not isinstance(value, dict):
                    raise ProtectedWorkerHttpError("protected worker request must be an object")
                return value

            @staticmethod
            def _parse_contract(value: Mapping[str, Any]) -> tuple[bool, ConfidentialEnvelope]:
                stream = value.get("stream", False)
                expected = {
                    "schema_version",
                    "confidential_protocol_version",
                    "envelope",
                }
                if stream is True:
                    expected.add("stream")
                elif stream is not False:
                    raise ProtectedWorkerHttpError("invalid protected stream flag")
                if set(value) != expected:
                    raise ProtectedWorkerHttpError("invalid protected worker wire contract")
                if value.get("schema_version") != 1 or value.get("confidential_protocol_version") != SCHEMA_VERSION:
                    raise ProtectedWorkerHttpError("protected worker protocol version mismatch")
                envelope_value = value.get("envelope")
                if not isinstance(envelope_value, Mapping):
                    raise ProtectedWorkerHttpError("protected worker envelope is missing")
                return bool(stream), ConfidentialEnvelope.from_dict(envelope_value)

            def _check_headers(self, envelope: ConfidentialEnvelope) -> None:
                protocol = self.headers.get("X-ComputeMesh-Confidential-Protocol")
                job = self.headers.get("X-ComputeMesh-Job-ID")
                node = self.headers.get("X-ComputeMesh-Node-ID")
                if protocol != str(envelope.schema_version):
                    raise ProtectedWorkerHttpError("protected protocol header mismatch")
                if job != envelope.binding.job_id or node != envelope.binding.node_id:
                    raise ProtectedWorkerHttpError("protected identity header mismatch")

            def _complete(self, envelope: ConfidentialEnvelope) -> None:
                result = manager.execute(envelope)
                if result.usage_receipt is None:
                    raise ProtectedWorkerHttpError("protected completion has no usage receipt")
                self._json(
                    HTTPStatus.OK,
                    {
                        "schema_version": 1,
                        "confidential_protocol_version": envelope.schema_version,
                        "response": result.response.to_dict(),
                        "usage_receipt": result.usage_receipt.to_dict(),
                    },
                )

            def _stream(self, envelope: ConfidentialEnvelope) -> None:
                iterator = iter(manager.stream(envelope))
                try:
                    first = next(iterator)
                except StopIteration as exc:
                    raise ProtectedWorkerHttpError("protected stream produced no frames") from exc
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Pragma", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                done = False
                for result in (first, *iterator):
                    is_done = result.usage_receipt is not None
                    if done:
                        raise ProtectedWorkerHttpError("protected stream produced data after final receipt")
                    event = {
                        "schema_version": 1,
                        "confidential_protocol_version": envelope.schema_version,
                        "type": "done" if is_done else "chunk",
                        "response": result.response.to_dict(),
                    }
                    if is_done:
                        event["usage_receipt"] = result.usage_receipt.to_dict()
                        done = True
                    raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
                    self.wfile.write(raw)
                    self.wfile.flush()
                if not done:
                    raise ProtectedWorkerHttpError("protected stream ended without final receipt")

            def _json(self, status: int, value: Mapping[str, Any]) -> None:
                raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Pragma", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: Any) -> None:
                return

        httpd = ThreadingHTTPServer((self.bind_host, self.bind_port), Handler)
        httpd.daemon_threads = True
        httpd.socket = self._context.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            name="cm-protected-worker-http",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
