"""Loopback-only OpenAI-compatible proxy for ComputeMesh protected inference.

Example:
    python -m apps.client.openai_proxy \
      --remote https://mesh.inetconnector.com \
      --attestation-policy ./confidential-attestation-policy.json

Then point an ordinary OpenAI client at http://127.0.0.1:11435/v1.
"""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse

from apps.client.confidential_openai import (
    ConfidentialOpenAIError,
    MAX_OPENAI_BODY_BYTES,
    is_loopback_host,
    load_local_attestation_policy,
)
from apps.client.confidential_openai_stream import (
    HttpStreamingProtectedTransport,
    StreamingConfidentialOpenAIBridge,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11435


class LocalOpenAIProxyHandler(BaseHTTPRequestHandler):
    """Plaintext exists here by design: this process is the local trusted boundary."""

    bridge: StreamingConfidentialOpenAIBridge | None = None
    transport: HttpStreamingProtectedTransport | None = None
    server_version = "ComputeMesh-Local-OpenAI/1"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        # Never log request paths/bodies from the plaintext boundary.
        return

    def _authorization(self) -> str:
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer ") or not value.removeprefix("Bearer ").strip():
            raise ConfidentialOpenAIError(
                "Missing bearer API key",
                status=401,
                error_type="authentication_error",
            )
        return value

    def _send_bytes(
        self,
        *,
        status: int,
        raw: bytes,
        content_type: str = "application/json",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def _send_json(self, value: dict[str, Any], *, status: int = 200) -> None:
        self._send_bytes(
            status=status,
            raw=json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )

    def _send_error(self, exc: ConfidentialOpenAIError) -> None:
        self._send_json(exc.openai_error(), status=exc.status)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ConfidentialOpenAIError(
                "Invalid Content-Length header",
                status=400,
                error_type="invalid_request_error",
            ) from exc
        if length <= 0 or length > MAX_OPENAI_BODY_BYTES:
            raise ConfidentialOpenAIError(
                "Invalid request payload size",
                status=413 if length > MAX_OPENAI_BODY_BYTES else 400,
                error_type="invalid_request_error",
            )
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ConfidentialOpenAIError(
                "Malformed JSON request body",
                status=400,
                error_type="invalid_request_error",
            ) from exc
        if not isinstance(value, dict):
            raise ConfidentialOpenAIError(
                "Request body must be a JSON object",
                status=400,
                error_type="invalid_request_error",
            )
        return value

    def do_GET(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
        try:
            if clean_path == "/healthz":
                self._send_json(
                    {
                        "status": "ok",
                        "service": "computemesh-local-openai",
                        "protected_plaintext_boundary": "local_process",
                    }
                )
                return
            authorization = self._authorization()
            if clean_path == "/v1/models":
                if self.transport is None:
                    raise ConfidentialOpenAIError("Local protected transport is not configured")
                status, raw, content_type = self.transport.get_models(authorization=authorization)
                self._send_bytes(status=status, raw=raw, content_type=content_type)
                return
            raise ConfidentialOpenAIError(
                "Not Found",
                status=404,
                error_type="invalid_request_error",
            )
        except ConfidentialOpenAIError as exc:
            self._send_error(exc)

    def _send_openai_stream(
        self,
        *,
        authorization: str,
        body: dict[str, Any],
        bridge: StreamingConfidentialOpenAIBridge,
    ) -> None:
        # The encrypted remote stream is not opened until bridge.stream() advances.
        stream = bridge.stream(authorization=authorization, body=body)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for chunk in stream:
                self.wfile.write(chunk)
                self.wfile.flush()
        except ConfidentialOpenAIError:
            # Once OpenAI SSE headers/chunks have started, changing to an HTTP JSON
            # error would corrupt the OpenAI stream contract.  Fail closed by ending
            # the connection without [DONE]; OpenAI clients surface an interrupted stream.
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass
            self.close_connection = True

    def do_POST(self) -> None:
        clean_path = urlparse(self.path).path.rstrip("/")
        try:
            if clean_path != "/v1/chat/completions":
                raise ConfidentialOpenAIError(
                    "Not Found",
                    status=404,
                    error_type="invalid_request_error",
                )
            authorization = self._authorization()
            body = self._read_json()
            bridge = self.bridge
            if bridge is None:
                raise ConfidentialOpenAIError("Local confidential bridge is not configured")
            stream_value = body.get("stream", False)
            if stream_value is True:
                self._send_openai_stream(
                    authorization=authorization,
                    body=body,
                    bridge=bridge,
                )
                return
            result = bridge.complete(authorization=authorization, body=body)
            self._send_json(result)
        except ConfidentialOpenAIError as exc:
            self._send_error(exc)


def create_proxy_server(
    *,
    host: str,
    port: int,
    bridge: StreamingConfidentialOpenAIBridge,
    transport: HttpStreamingProtectedTransport,
) -> tuple[ThreadingHTTPServer, int]:
    if not is_loopback_host(host):
        raise ValueError("The protected OpenAI proxy must bind to loopback only")

    class BoundHandler(LocalOpenAIProxyHandler):
        pass

    BoundHandler.bridge = bridge
    BoundHandler.transport = transport
    server = ThreadingHTTPServer((host, port), BoundHandler)
    return server, int(server.server_address[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Loopback OpenAI-compatible ComputeMesh confidential transport"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--remote", required=True, help="Remote ComputeMesh HTTPS base URL")
    parser.add_argument("--ca-file", default="")
    parser.add_argument("--attestation-policy", required=True)
    parser.add_argument(
        "--privacy",
        choices=("CONFIDENTIAL", "CRYPTO_PRIVATE"),
        default="CONFIDENTIAL",
    )
    args = parser.parse_args(argv)
    if not is_loopback_host(args.host):
        print("refusing non-loopback protected proxy bind", file=sys.stderr)
        return 2
    try:
        policy = load_local_attestation_policy(Path(args.attestation_policy))
        transport = HttpStreamingProtectedTransport(
            base_url=args.remote,
            ca_file=Path(args.ca_file) if args.ca_file else None,
        )
        bridge = StreamingConfidentialOpenAIBridge(
            transport=transport,
            attestation_policy=policy,
            privacy_class=args.privacy,
        )
        server, bound_port = create_proxy_server(
            host=args.host,
            port=args.port,
            bridge=bridge,
            transport=transport,
        )
    except Exception as exc:
        print(f"protected OpenAI proxy startup failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"ComputeMesh protected OpenAI API listening on http://{args.host}:{bound_port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
