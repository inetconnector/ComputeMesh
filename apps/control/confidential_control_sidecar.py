#!/usr/bin/env python3
"""Local bridge between the private policy service and provider NodeSessions.

The sidecar owns the *single* persistent TLS + Ed25519 provider-control channel.
Its HTTP API is loopback-only, content-free and intended solely for the private
ComputeMesh ControlPlane process. It exposes no ranking inputs or prompt content.
"""
from __future__ import annotations

import argparse
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any, Mapping

from protocol.node_identity import Ed25519ChallengeVerifier
from runtime.confidential.provider_control import CONFIDENTIAL_PROVISION_MESSAGE
from services.identity.store import SQLiteIdentityStore
from services.orchestrator.confidential_live_registry import ConfidentialLiveRuntimeRegistry
from services.orchestrator.live_control_plane import IntegratedLiveControlPlane


MAX_SIDECAR_BODY_BYTES = 256 * 1024
CANDIDATES_PATH = "/internal/v1/confidential/candidates"
PROVISION_PATH = "/internal/v1/confidential/provision"


class ConfidentialControlSidecarError(RuntimeError):
    pass


def _loopback_host(value: str) -> str:
    host = value.strip().lower()
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("confidential sidecar HTTP must bind to loopback")
    return value


class ConfidentialControlSidecar:
    def __init__(
        self,
        *,
        registry: ConfidentialLiveRuntimeRegistry,
        bearer_token: str,
        host: str = "127.0.0.1",
        port: int = 8743,
        provision_timeout_seconds: float = 20.0,
    ) -> None:
        if not bearer_token or len(bearer_token) > 4096:
            raise ValueError("confidential sidecar bearer token is invalid")
        _loopback_host(host)
        if not 1 <= port <= 65535:
            raise ValueError("confidential sidecar port is invalid")
        if not 0.5 <= provision_timeout_seconds <= 120.0:
            raise ValueError("confidential sidecar timeout is invalid")
        self.registry = registry
        self.bearer_token = bearer_token
        self.host = host
        self.port = port
        self.provision_timeout_seconds = float(provision_timeout_seconds)

    def serve_forever(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ComputeMesh-ConfidentialControlSidecar/1"

            def _authorized(self) -> bool:
                value = self.headers.get("Authorization", "")
                prefix = "Bearer "
                return value.startswith(prefix) and hmac.compare_digest(
                    value[len(prefix) :], owner.bearer_token
                )

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

            def _body(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ConfidentialControlSidecarError("invalid request length") from exc
                if not 1 <= length <= MAX_SIDECAR_BODY_BYTES:
                    raise ConfidentialControlSidecarError("invalid request size")
                try:
                    value = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ConfidentialControlSidecarError("invalid request JSON") from exc
                if not isinstance(value, dict):
                    raise ConfidentialControlSidecarError("request root must be an object")
                return value

            def do_GET(self) -> None:
                if self.path != CANDIDATES_PATH:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                if not self._authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                candidates = owner.registry.confidential_candidates()
                self._json(
                    HTTPStatus.OK,
                    {
                        "schema_version": 1,
                        "candidates": [
                            {
                                "node_id": item.node_id,
                                "session_id": item.session.session_id,
                                "session_revision": item.session.revision,
                            }
                            for item in candidates
                        ],
                    },
                )

            def do_POST(self) -> None:
                if self.path != PROVISION_PATH:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                if not self._authorized():
                    self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                try:
                    body = self._body()
                    expected = {
                        "schema_version",
                        "node_id",
                        "session_id",
                        "session_revision",
                        "freshness_challenge",
                        "request",
                    }
                    if set(body) != expected or body.get("schema_version") != 1:
                        raise ConfidentialControlSidecarError("invalid provision contract")
                    node_id = body.get("node_id")
                    session_id = body.get("session_id")
                    revision = body.get("session_revision")
                    challenge = body.get("freshness_challenge")
                    request = body.get("request")
                    if not isinstance(node_id, str) or not node_id or len(node_id) > 256:
                        raise ConfidentialControlSidecarError("invalid provision node")
                    if not isinstance(session_id, str) or not session_id:
                        raise ConfidentialControlSidecarError("invalid provision control session")
                    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
                        raise ConfidentialControlSidecarError("invalid provision session revision")
                    if not isinstance(challenge, str) or not challenge or len(challenge) > 256:
                        raise ConfidentialControlSidecarError("invalid provision freshness challenge")
                    if not isinstance(request, dict):
                        raise ConfidentialControlSidecarError("invalid provision request")
                    candidates = {
                        item.node_id: item for item in owner.registry.confidential_candidates()
                    }
                    selected = candidates.get(node_id)
                    if selected is None:
                        raise ConfidentialControlSidecarError("selected confidential provider is no longer live")
                    if selected.session.session_id != session_id or selected.session.revision != revision:
                        raise ConfidentialControlSidecarError("selected provider control session changed")
                    response = owner.registry.control_client.request(
                        node_id,
                        message_type=CONFIDENTIAL_PROVISION_MESSAGE,
                        payload={
                            "session_id": session_id,
                            "session_revision": revision,
                            "freshness_challenge": challenge,
                            "request": request,
                        },
                        timeout_seconds=owner.provision_timeout_seconds,
                    )
                    if not isinstance(response, dict):
                        raise ConfidentialControlSidecarError("provider returned invalid provision response")
                    self._json(HTTPStatus.OK, response)
                except Exception:
                    self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "confidential_provision_unavailable"})

            def log_message(self, format: str, *args: Any) -> None:
                return

        httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        httpd.daemon_threads = True
        httpd.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the private-local confidential control sidecar")
    parser.add_argument("--identity-db", type=Path, required=True)
    parser.add_argument("--provider-host", required=True)
    parser.add_argument("--provider-port", type=int, default=7443)
    parser.add_argument("--provider-tls-cert", required=True)
    parser.add_argument("--provider-tls-key", required=True)
    parser.add_argument("--sidecar-host", default="127.0.0.1")
    parser.add_argument("--sidecar-port", type=int, default=8743)
    parser.add_argument("--sidecar-token", required=True)
    parser.add_argument("--provision-timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    registry = ConfidentialLiveRuntimeRegistry()
    identity = SQLiteIdentityStore(args.identity_db)
    verifier = Ed25519ChallengeVerifier(identity)
    control = IntegratedLiveControlPlane(
        registry=registry,
        verifier=verifier,
        host=args.provider_host,
        port=args.provider_port,
        cert_file=args.provider_tls_cert,
        key_file=args.provider_tls_key,
    )
    sidecar = ConfidentialControlSidecar(
        registry=registry,
        bearer_token=args.sidecar_token,
        host=args.sidecar_host,
        port=args.sidecar_port,
        provision_timeout_seconds=args.provision_timeout,
    )
    control.start()
    try:
        sidecar.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        control.close()
        identity.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
