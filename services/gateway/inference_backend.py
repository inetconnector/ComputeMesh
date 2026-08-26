"""Inference backends for the public ComputeMesh gateway.

Production requests must execute against a configured runtime endpoint. Synthetic
responses are available only through an explicit opt-in intended for tests/dev.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Protocol
from urllib import error, request
from urllib.parse import urlparse


class InferenceBackendError(RuntimeError):
    """Raised when a configured inference backend cannot produce a valid result."""


@dataclass(frozen=True)
class BackendResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


class InferenceBackend(Protocol):
    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        """Execute one non-streaming chat completion."""


class DisabledInferenceBackend:
    """Fail closed when no real inference backend is configured."""

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        raise InferenceBackendError(
            "Inference backend is not configured. Set COMPUTEMESH_INFERENCE_BACKEND "
            "and COMPUTEMESH_INFERENCE_URL before serving inference traffic."
        )


class SyntheticInferenceBackend:
    """Deterministic backend for tests and explicitly opted-in development only."""

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        last_user_msg = ""
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                last_user_msg = str(message.get("content", ""))
                break
        # Keep legacy fixture text so existing gateway contract tests remain useful,
        # while production can no longer reach this backend without explicit opt-in.
        text = (
            f"ComputeMesh distributed response for: {last_user_msg[:60]}"
            if last_user_msg
            else "Hello from ComputeMesh decentralized inference!"
        )
        return BackendResult(
            text=text,
            prompt_tokens=max(len(json.dumps(messages)) // 4, 8),
            completion_tokens=max(len(text) // 4, 12),
        )


class OpenAICompatibleHTTPBackend:
    """Call a llama.cpp/OpenAI-compatible HTTP chat-completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_response_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("COMPUTEMESH_INFERENCE_URL must be an http(s) URL")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        payload = json.dumps(
            {"model": model_id, "messages": messages, "stream": False},
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
            raise InferenceBackendError("Inference runtime request failed") from exc

        if len(raw) > self.max_response_bytes:
            raise InferenceBackendError("Inference runtime response exceeded size limit")
        try:
            body = json.loads(raw.decode("utf-8"))
            text = body["choices"][0]["message"]["content"]
            usage = body["usage"]
            prompt_tokens = int(usage["prompt_tokens"])
            completion_tokens = int(usage["completion_tokens"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise InferenceBackendError("Inference runtime returned an invalid response") from exc

        if not isinstance(text, str) or prompt_tokens < 0 or completion_tokens < 0:
            raise InferenceBackendError("Inference runtime returned invalid content or usage")
        return BackendResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )


def build_inference_backend_from_env() -> InferenceBackend:
    """Build the configured gateway backend using secure fail-closed defaults."""
    backend = os.environ.get("COMPUTEMESH_INFERENCE_BACKEND", "disabled").strip().lower()
    if backend in {"", "disabled", "none"}:
        return DisabledInferenceBackend()
    if backend in {"openai", "openai-compatible", "openai_compatible", "llama.cpp", "llama_cpp"}:
        base_url = os.environ.get("COMPUTEMESH_INFERENCE_URL", "").strip()
        if not base_url:
            raise InferenceBackendError(
                "COMPUTEMESH_INFERENCE_URL is required for the OpenAI-compatible backend"
            )
        try:
            timeout = float(os.environ.get("COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS", "120"))
        except ValueError as exc:
            raise InferenceBackendError("Invalid COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS") from exc
        return OpenAICompatibleHTTPBackend(
            base_url=base_url,
            api_key=os.environ.get("COMPUTEMESH_INFERENCE_API_KEY") or None,
            timeout_seconds=timeout,
        )
    if backend == "synthetic":
        if os.environ.get("COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE", "").strip() != "1":
            raise InferenceBackendError(
                "Synthetic inference requires COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE=1"
            )
        return SyntheticInferenceBackend()
    raise InferenceBackendError(f"Unsupported inference backend: {backend}")
