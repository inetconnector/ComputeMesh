"""Loopback-only HTTP bridge to authenticated live provider GPU promo sessions.

The live gateway process owns the persistent Ed25519-authenticated provider control
channels. Other local ComputeMesh services must not open a second provider channel;
they may use this narrow bearer-authenticated bridge to read the enrolled key id
proven by the live session and to dispatch one already-private-policy-selected GPU
work document to that same session.
"""
from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from services.orchestrator.authenticated_gpu_promo_transport import (
    AuthenticatedGpuPromoTransportError,
    SessionAuthenticatedGpuPromoTransport,
)

_DISPATCH_PATH = "/internal/v1/promo/gpu-dispatch"
_SESSION_PATH = "/internal/v1/promo/gpu-session"
_MAX_REQUEST_BYTES = 256 * 1024


class GpuPromoDispatchError(ValueError):
    pass


@dataclass
class GpuPromoDispatchService:
    transport: SessionAuthenticatedGpuPromoTransport
    bearer_token: str

    def __post_init__(self) -> None:
        self.bearer_token = self.bearer_token.strip()
        if len(self.bearer_token) < 24:
            raise ValueError("GPU promo dispatch token must be at least 24 characters")

    def _authorize(self, authorization: str) -> None:
        prefix = "Bearer "
        supplied = str(authorization or "")
        if not supplied.startswith(prefix) or not hmac.compare_digest(
            supplied[len(prefix) :], self.bearer_token
        ):
            raise GpuPromoDispatchError("unauthorized")

    @staticmethod
    def _node_id(body: dict[str, Any]) -> str:
        node_id = body.get("node_id")
        if not isinstance(node_id, str) or not 1 <= len(node_id) <= 128:
            raise GpuPromoDispatchError("invalid GPU promo node id")
        return node_id

    def session_identity(
        self,
        *,
        body: dict[str, Any],
        authorization: str,
    ) -> dict[str, Any]:
        """Return only the node/key binding proven by the authenticated live session."""
        self._authorize(authorization)
        if set(body) != {"node_id"}:
            raise GpuPromoDispatchError("invalid GPU promo session contract")
        node_id = self._node_id(body)
        try:
            key_id = self.transport.authenticated_key_id(node_id)
        except AuthenticatedGpuPromoTransportError as exc:
            raise GpuPromoDispatchError("GPU promo provider dispatch failed") from exc
        if not isinstance(key_id, str) or not 1 <= len(key_id) <= 128:
            raise GpuPromoDispatchError("GPU promo provider dispatch failed")
        return {"node_id": node_id, "key_id": key_id}

    def dispatch(
        self,
        *,
        body: dict[str, Any],
        authorization: str,
    ) -> dict[str, Any]:
        self._authorize(authorization)
        if set(body) != {"node_id", "challenge"}:
            raise GpuPromoDispatchError("invalid GPU promo dispatch contract")
        node_id = self._node_id(body)
        challenge = body.get("challenge")
        if not isinstance(challenge, dict) or challenge.get("node_id") != node_id:
            raise GpuPromoDispatchError("GPU promo challenge node binding mismatch")
        timeout_ms = challenge.get("timeout_ms")
        if (
            isinstance(timeout_ms, bool)
            or not isinstance(timeout_ms, int)
            or not 1_000 <= timeout_ms <= 300_000
        ):
            raise GpuPromoDispatchError("invalid GPU promo challenge timeout")

        try:
            result = self.transport.request_gpu_promo_challenge(
                node_id=node_id,
                challenge_document=challenge,
                timeout_seconds=min(300.0, timeout_ms / 1000.0 + 2.0),
            )
        except (AuthenticatedGpuPromoTransportError, ValueError) as exc:
            raise GpuPromoDispatchError("GPU promo provider dispatch failed") from exc

        return {
            "proof": result.proof,
            "gpu_observation": {
                "server_roundtrip_ms": result.server_roundtrip_ms,
                "session_id": result.session_id,
                "session_revision": result.session_revision,
            },
        }


class _GpuPromoDispatchHandler(BaseHTTPRequestHandler):
    service: GpuPromoDispatchService
    server_version = "ComputeMesh-GpuPromoDispatch/0.1"

    def _json(self, status: int, value: dict[str, Any]) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path not in {_DISPATCH_PATH, _SESSION_PATH}:
            self._json(404, {"error": "not_found"})
            return
        try:
            raw_length = self.headers.get("Content-Length", "")
            length = int(raw_length)
            if length < 1 or length > _MAX_REQUEST_BYTES:
                raise ValueError("invalid request size")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("request root must be an object")
            if self.path == _SESSION_PATH:
                result = self.service.session_identity(
                    body=body,
                    authorization=self.headers.get("Authorization", ""),
                )
            else:
                result = self.service.dispatch(
                    body=body,
                    authorization=self.headers.get("Authorization", ""),
                )
        except GpuPromoDispatchError as exc:
            if str(exc) == "unauthorized":
                self._json(401, {"error": "unauthorized"})
            elif str(exc) == "GPU promo provider dispatch failed":
                self._json(503, {"error": "provider_dispatch_unavailable"})
            else:
                self._json(400, {"error": "invalid_gpu_promo_dispatch"})
            return
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self._json(400, {"error": "invalid_request"})
            return
        self._json(200, result)

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_gpu_promo_dispatch_server(
    *,
    transport: SessionAuthenticatedGpuPromoTransport,
    bearer_token: str,
    port: int,
) -> ThreadingHTTPServer:
    """Create an intentionally plaintext loopback-only bridge.

    A non-loopback deployment must use a different TLS/service-mesh transport rather
    than weakening this helper.
    """
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("GPU promo dispatch port must be 0..65535")
    service = GpuPromoDispatchService(transport=transport, bearer_token=bearer_token)

    class Handler(_GpuPromoDispatchHandler):
        pass

    Handler.service = service
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


__all__ = [
    "GpuPromoDispatchError",
    "GpuPromoDispatchService",
    "create_gpu_promo_dispatch_server",
]
