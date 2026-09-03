"""OpenAI-compatible backend adapter for the protected worker boundary.

Plaintext is permitted only on loopback and only when that backend is part of the
same attested workload measurement. The adapter never follows remote redirects and
never logs request or response bodies.
"""
from __future__ import annotations

import json
import socket
from typing import Any, Iterator, Mapping
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from runtime.confidential.protected_worker import ProtectedWorkerError


MAX_BACKEND_BODY_BYTES = 8 * 1024 * 1024
MAX_SSE_LINE_BYTES = 2 * 1024 * 1024


class _NoRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urlerror.HTTPError(req.full_url, code, "redirect forbidden", headers, fp)


class LoopbackOpenAIBackend:
    """Forward decrypted OpenAI JSON to an attested loopback runtime."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 120.0) -> None:
        parsed = urlparse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("protected backend URL must be HTTP(S) loopback")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("protected backend URL contains forbidden components")
        if not _is_loopback(parsed.hostname):
            raise ValueError("protected plaintext backend must be loopback")
        if not 0.5 <= float(timeout_seconds) <= 600.0:
            raise ValueError("protected backend timeout must be between 0.5 and 600 seconds")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self._opener = urlrequest.build_opener(_NoRedirect())

    def complete(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        body = dict(request)
        body["stream"] = False
        raw = self._post_json(body, accept="application/json")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProtectedWorkerError("protected backend returned malformed OpenAI JSON") from exc
        if not isinstance(value, dict):
            raise ProtectedWorkerError("protected backend returned a non-object OpenAI response")
        return value

    def stream(self, request: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
        body = dict(request)
        body["stream"] = True
        stream_options = body.get("stream_options")
        if stream_options is None:
            stream_options = {}
        if not isinstance(stream_options, Mapping):
            raise ProtectedWorkerError("OpenAI stream_options must be an object")
        body["stream_options"] = {**dict(stream_options), "include_usage": True}
        encoded = _encode(body)
        req = urlrequest.Request(
            self.base_url + "/v1/chat/completions",
            data=encoded,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Content-Length": str(len(encoded)),
                "Connection": "close",
            },
        )
        try:
            response = self._opener.open(req, timeout=self.timeout_seconds)
        except (urlerror.URLError, urlerror.HTTPError, TimeoutError, OSError) as exc:
            raise ProtectedWorkerError("protected OpenAI backend stream is unavailable") from exc
        with response:
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "text/event-stream":
                raise ProtectedWorkerError("protected backend did not return OpenAI SSE")
            done = False
            while True:
                line = response.readline(MAX_SSE_LINE_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_SSE_LINE_BYTES:
                    raise ProtectedWorkerError("protected backend SSE frame is too large")
                line = line.strip()
                if not line or line.startswith(b":"):
                    continue
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    done = True
                    break
                try:
                    value = json.loads(payload.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ProtectedWorkerError("protected backend SSE JSON is malformed") from exc
                if not isinstance(value, dict):
                    raise ProtectedWorkerError("protected backend SSE chunk must be an object")
                yield value
            if not done:
                raise ProtectedWorkerError("protected backend stream ended without [DONE]")

    def _post_json(self, body: Mapping[str, Any], *, accept: str) -> bytes:
        encoded = _encode(body)
        req = urlrequest.Request(
            self.base_url + "/v1/chat/completions",
            data=encoded,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": accept,
                "Content-Length": str(len(encoded)),
                "Connection": "close",
            },
        )
        try:
            with self._opener.open(req, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_BACKEND_BODY_BYTES + 1)
        except (urlerror.URLError, urlerror.HTTPError, TimeoutError, OSError) as exc:
            raise ProtectedWorkerError("protected OpenAI backend is unavailable") from exc
        if len(raw) > MAX_BACKEND_BODY_BYTES:
            raise ProtectedWorkerError("protected backend response exceeds size limit")
        return raw


def _encode(value: Mapping[str, Any]) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProtectedWorkerError("protected OpenAI request is not JSON serializable") from exc
    if not raw or len(raw) > MAX_BACKEND_BODY_BYTES:
        raise ProtectedWorkerError("protected OpenAI request exceeds size limit")
    return raw


def _is_loopback(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return all(item[4][0] in {"127.0.0.1", "::1"} for item in socket.getaddrinfo(host, None))
    except OSError:
        return False
