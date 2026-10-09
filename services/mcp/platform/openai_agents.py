"""Optional server-side adapter for the OpenAI Agents API.

This adapter is deliberately separate from the local MeshAgentHarness. Local
sessions, policy, approvals and event persistence remain authoritative; a
deployment may opt into this provider for selected sessions without making an
OpenAI credential available to a phone, node or model workspace.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


class OpenAIAgentsProviderError(RuntimeError):
    """Raised when the optional provider cannot complete a request."""


@dataclass(frozen=True)
class OpenAIAgentsConfig:
    base_url: str = "https://api.openai.com"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 30.0
    max_request_bytes: int = 4 * 1024 * 1024
    max_response_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        parsed = urlparse(str(self.base_url).rstrip("/"))
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("OpenAI Agents base_url must be an absolute HTTP(S) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("OpenAI Agents base_url must use HTTPS outside loopback")
        if not str(self.api_key_env).strip() or not str(self.api_key_env).replace("_", "").isalnum():
            raise ValueError("api_key_env must be a simple environment variable name")
        if isinstance(self.timeout_seconds, bool) or float(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        for field_name in ("max_request_bytes", "max_response_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or int(value) <= 0:
                raise ValueError(f"{field_name} must be positive")

    @classmethod
    def from_env(cls) -> "OpenAIAgentsConfig":
        return cls(
            base_url=os.getenv("COMPUTEMESH_OPENAI_AGENTS_BASE_URL", cls.base_url),
            api_key_env=os.getenv("COMPUTEMESH_OPENAI_AGENTS_API_KEY_ENV", cls.api_key_env),
        )


class OpenAIAgentsClient:
    """Bounded HTTP client for the optional Agents API session surface."""

    def __init__(
        self,
        config: OpenAIAgentsConfig | None = None,
        *,
        opener: Callable[..., Any] = urlopen,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config or OpenAIAgentsConfig.from_env()
        self._opener = opener
        self._environ = os.environ if environ is None else environ

    @property
    def enabled(self) -> bool:
        return bool(str(self._environ.get(self.config.api_key_env, "")).strip())

    def _api_key(self) -> str:
        key = str(self._environ.get(self.config.api_key_env, "")).strip()
        if not key:
            raise OpenAIAgentsProviderError("optional OpenAI Agents provider is not configured")
        return key

    @staticmethod
    def _session_id(value: str) -> str:
        clean = str(value or "").strip()
        if not clean or len(clean) > 200 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-" for char in clean):
            raise ValueError("invalid OpenAI Agents session id")
        return clean

    def _url(self, path: str, query: Mapping[str, Any] | None = None) -> str:
        base = str(self.config.base_url).rstrip("/")
        result = f"{base}/{path.lstrip('/')}"
        if query:
            result += "?" + urlencode({key: value for key, value in query.items() if value is not None})
        return result

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        accept: str = "application/json",
        idempotency_key: str | None = None,
    ) -> Any:
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(body) > self.config.max_request_bytes:
                raise OpenAIAgentsProviderError("OpenAI Agents request exceeds the configured size limit")
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self._api_key()}",
            "OpenAI-Beta": "agents=v1",
            "User-Agent": "ComputeMesh-AgentsProvider/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = self._validate_idempotency_key(idempotency_key)
        request = Request(self._url(path, query), data=body, headers=headers, method=method.upper())
        try:
            response = self._opener(request, timeout=float(self.config.timeout_seconds))
            raw = response.read(self.config.max_response_bytes + 1)
        except HTTPError as exc:
            try:
                raw = exc.read(self.config.max_response_bytes + 1)
                detail = json.loads(raw[: self.config.max_response_bytes].decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                detail = ""
            raise OpenAIAgentsProviderError(f"OpenAI Agents request failed ({exc.code})" + (f": {detail[:240]}" if detail else "")) from exc
        except (OSError, URLError, TimeoutError) as exc:
            raise OpenAIAgentsProviderError("OpenAI Agents provider is unavailable") from exc
        if len(raw) > self.config.max_response_bytes:
            raise OpenAIAgentsProviderError("OpenAI Agents response exceeds the configured size limit")
        if not raw:
            return {}
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenAIAgentsProviderError("OpenAI Agents returned invalid JSON") from exc
        if not isinstance(result, (dict, list)):
            raise OpenAIAgentsProviderError("OpenAI Agents returned an invalid response")
        return result

    def create_session(
        self,
        agent: Mapping[str, Any],
        input: str,
        *,
        environment: Mapping[str, Any] | None = None,
        stream: bool = False,
        idempotency_key: str | None = None,
    ) -> Any:
        if not isinstance(agent, Mapping) or not str(agent.get("model") or "").strip():
            raise ValueError("agent.model is required")
        clean_input = str(input or "").strip()
        if not clean_input:
            raise ValueError("input is required")
        payload: dict[str, Any] = {"agent": dict(agent), "input": clean_input, "stream": bool(stream)}
        if environment is not None:
            payload["environment"] = dict(environment)
        if stream:
            return self._stream_request("POST", "/v1/agents/sessions", payload, idempotency_key=idempotency_key)
        return self._request("POST", "/v1/agents/sessions", payload=payload, idempotency_key=idempotency_key)

    def send_message(self, session_id: str, input: str, *, idempotency_key: str | None = None) -> Any:
        clean_input = str(input or "").strip()
        if not clean_input:
            raise ValueError("input is required")
        payload = {
            "events": [{
                "type": "agent.session.input.message",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": clean_input}]}],
            }]
        }
        return self._request(
            "POST",
            f"/v1/agents/sessions/{quote(self._session_id(session_id), safe='')}/events",
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def cancel_turn(self, session_id: str, *, idempotency_key: str | None = None) -> Any:
        return self._request(
            "POST",
            f"/v1/agents/sessions/{quote(self._session_id(session_id), safe='')}/events",
            payload={"events": [{"type": "agent.session.input.cancel"}]},
            idempotency_key=idempotency_key,
        )

    def retrieve_session(self, session_id: str) -> Any:
        return self._request("GET", f"/v1/agents/sessions/{quote(self._session_id(session_id), safe='')}")

    def list_items(self, session_id: str, *, after: str | None = None, limit: int = 100) -> Any:
        bounded_limit = max(1, min(int(limit), 100))
        return self._request(
            "GET",
            f"/v1/agents/sessions/{quote(self._session_id(session_id), safe='')}/items",
            query={"order": "asc", "limit": bounded_limit, "after": after},
        )

    def stream_events(self, session_id: str) -> Iterator[dict[str, Any]]:
        return self._stream_request(
            "GET",
            f"/v1/agents/sessions/{quote(self._session_id(session_id), safe='')}/events",
            None,
        )

    def _stream_request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        *,
        idempotency_key: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if body is not None and len(body) > self.config.max_request_bytes:
            raise OpenAIAgentsProviderError("OpenAI Agents request exceeds the configured size limit")
        headers = {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self._api_key()}",
            "OpenAI-Beta": "agents=v1",
            "User-Agent": "ComputeMesh-AgentsProvider/1",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = self._validate_idempotency_key(idempotency_key)
        request = Request(self._url(path), data=body, headers=headers, method=method.upper())

        def events() -> Iterator[dict[str, Any]]:
            try:
                response = self._opener(request, timeout=float(self.config.timeout_seconds))
                total = 0
                data_lines: list[str] = []
                while True:
                    line = response.readline()
                    if not line:
                        break
                    total += len(line)
                    if total > self.config.max_response_bytes:
                        raise OpenAIAgentsProviderError("OpenAI Agents event stream exceeds the configured size limit")
                    text = line.decode("utf-8", errors="strict").rstrip("\r\n")
                    if not text:
                        if data_lines:
                            try:
                                event = json.loads("\n".join(data_lines))
                            except json.JSONDecodeError as exc:
                                raise OpenAIAgentsProviderError("OpenAI Agents returned an invalid event") from exc
                            if isinstance(event, dict):
                                yield event
                            data_lines = []
                        continue
                    if text.startswith("data:"):
                        value = text[5:].lstrip()
                        if value and value != "[DONE]":
                            data_lines.append(value)
                if data_lines:
                    event = json.loads("\n".join(data_lines))
                    if isinstance(event, dict):
                        yield event
            except HTTPError as exc:
                raise OpenAIAgentsProviderError(f"OpenAI Agents stream failed ({exc.code})") from exc
            except (OSError, URLError, TimeoutError) as exc:
                raise OpenAIAgentsProviderError("OpenAI Agents stream is unavailable") from exc

        return events()

    @staticmethod
    def _validate_idempotency_key(value: str) -> str:
        if len(value) > 200 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-" for char in value):
            raise ValueError("invalid OpenAI Agents idempotency key")
        return value


__all__ = ["OpenAIAgentsConfig", "OpenAIAgentsClient", "OpenAIAgentsProviderError"]
