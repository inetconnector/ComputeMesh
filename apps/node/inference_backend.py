"""Bounded loopback adapter from the provider agent to the local NodeOS runtime."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

from protocol.node_session import SessionSnapshot


class LocalInferenceError(RuntimeError):
    """Raised when the configured local model runtime cannot serve a request."""


def _is_loopback(hostname: str | None) -> bool:
    return str(hostname or "").lower().rstrip(".") in {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class LocalOpenAIInferenceBackend:
    """Call one local OpenAI-compatible endpoint without exposing its credential."""

    endpoint: str
    auth_token: str | None = None
    timeout_seconds: float = 120.0
    max_response_bytes: int = 8 * 1024 * 1024
    on_cancel: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not _is_loopback(parsed.hostname):
            raise ValueError("inference endpoint must be an HTTP(S) loopback URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("inference endpoint must not contain credentials or query data")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        if self.max_response_bytes < 1024 or self.max_response_bytes > 64 * 1024 * 1024:
            raise ValueError("max_response_bytes is outside the allowed range")
        if self.on_cancel is not None and not callable(self.on_cancel):
            raise ValueError("on_cancel must be callable")

    @staticmethod
    def _watch_cancellation(
        response: Any,
        cancel_event: Any | None,
        on_cancel: Callable[[], None] | None = None,
    ) -> tuple[threading.Event, threading.Thread] | None:
        """Close the response and optionally stop the deployment-owned runtime."""
        if cancel_event is None or not callable(getattr(cancel_event, "is_set", None)):
            return None
        stop_event = threading.Event()

        def watch() -> None:
            while not stop_event.wait(0.05):
                if not cancel_event.is_set():
                    continue
                close = getattr(response, "close", None)
                if callable(close):
                    try:
                        close()
                    except OSError:
                        pass
                if on_cancel is not None:
                    try:
                        on_cancel()
                    except Exception:
                        # Cancellation must still propagate when a deployment hook fails.
                        pass
                return

        thread = threading.Thread(target=watch, name="ComputeMesh-local-inference-cancel", daemon=True)
        thread.start()
        return stop_event, thread

    @staticmethod
    def _stop_cancellation_watcher(watcher: tuple[threading.Event, threading.Thread] | None) -> None:
        if watcher is None:
            return
        watcher[0].set()
        watcher[1].join(timeout=1.0)

    def __call__(
        self,
        session: SessionSnapshot,
        request: Mapping[str, Any],
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            raise LocalInferenceError("local model inference was cancelled")
        body = {
            "model": request["model_id"],
            "messages": [dict(message) for message in request["messages"]],
            "max_tokens": request["max_tokens"],
            "stream": False,
        }
        if "temperature" in request:
            body["temperature"] = request["temperature"]
        if request.get("tools"):
            body["tools"] = [dict(tool) for tool in request["tools"]]
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_obj = urlrequest.Request(self.endpoint, data=encoded, headers=headers, method="POST")
        try:
            response = urlrequest.urlopen(request_obj, timeout=self.timeout_seconds)
            watcher = self._watch_cancellation(response, cancel_event, self.on_cancel)
            try:
                with response:
                    raw = response.read(self.max_response_bytes + 1)
            finally:
                self._stop_cancellation_watcher(watcher)
        except urlerror.HTTPError as exc:
            raise LocalInferenceError(f"local model runtime returned HTTP {exc.code}") from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise LocalInferenceError("local model inference was cancelled") from exc
            raise LocalInferenceError("local model runtime is unavailable") from exc
        if cancel_event is not None and cancel_event.is_set():
            raise LocalInferenceError("local model inference was cancelled")
        if len(raw) > self.max_response_bytes:
            raise LocalInferenceError("local model runtime response exceeds the size limit")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LocalInferenceError("local model runtime returned invalid JSON") from exc
        if not isinstance(document, Mapping):
            raise LocalInferenceError("local model runtime returned a non-object")
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise LocalInferenceError("local model runtime returned no completion choice")
        message = choices[0].get("message")
        output = message.get("content") if isinstance(message, Mapping) else None
        tool_calls = self._normalize_tool_calls(message.get("tool_calls") if isinstance(message, Mapping) else None)
        if output is None and tool_calls:
            output = ""
        if not isinstance(output, str) or len(output) > 4 * 1024 * 1024:
            raise LocalInferenceError("local model runtime returned invalid completion content")
        usage = document.get("usage")
        normalized_usage: dict[str, int] | None = None
        if isinstance(usage, Mapping):
            normalized_usage = self._normalize_usage(usage)
        result: dict[str, Any] = {
            "schema_version": 1,
            "session_id": str(request["session_id"]),
            "turn_id": str(request["turn_id"]),
            "lease_id": str(request["lease_id"]),
            "node_id": str(session.node_id),
            "model_id": str(request["model_id"]),
            "output": output,
        }
        if normalized_usage is not None:
            result["usage"] = normalized_usage
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    @staticmethod
    def _normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 32:
            raise LocalInferenceError("local model runtime returned invalid tool calls")
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping) or item.get("type") != "function":
                raise LocalInferenceError("local model runtime returned an invalid tool call")
            function = item.get("function")
            if not isinstance(function, Mapping):
                raise LocalInferenceError("local model runtime returned an invalid tool function")
            call_id = item.get("id")
            name = function.get("name")
            arguments = function.get("arguments")
            if (
                not isinstance(call_id, str) or not 1 <= len(call_id) <= 160
                or not isinstance(name, str) or not 1 <= len(name) <= 256
                or not isinstance(arguments, str) or len(arguments) > 131072
            ):
                raise LocalInferenceError("local model runtime returned an invalid tool function")
            normalized.append({
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            })
        return normalized

    def stream(
        self,
        session: SessionSnapshot,
        request: Mapping[str, Any],
        cancel_event: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        body = {
            "model": request["model_id"],
            "messages": [dict(message) for message in request["messages"]],
            "max_tokens": request["max_tokens"],
            "stream": True,
        }
        if "temperature" in request:
            body["temperature"] = request["temperature"]
        if request.get("tools"):
            body["tools"] = [dict(tool) for tool in request["tools"]]
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_obj = urlrequest.Request(self.endpoint, data=encoded, headers=headers, method="POST")
        try:
            response = urlrequest.urlopen(request_obj, timeout=self.timeout_seconds)
        except urlerror.HTTPError as exc:
            raise LocalInferenceError(f"local model runtime returned HTTP {exc.code}") from exc
        except (urlerror.URLError, TimeoutError, OSError) as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise LocalInferenceError("local model inference stream was cancelled") from exc
            raise LocalInferenceError("local model runtime is unavailable") from exc

        watcher = self._watch_cancellation(response, cancel_event, self.on_cancel)
        total_bytes = 0
        emitted_done = False
        try:
            while True:
                try:
                    line = response.readline()
                except OSError as exc:
                    if cancel_event is not None and cancel_event.is_set():
                        raise LocalInferenceError("local model inference stream was cancelled") from exc
                    raise LocalInferenceError("local model runtime stream is unavailable") from exc
                if cancel_event is not None and cancel_event.is_set():
                    raise LocalInferenceError("local model inference stream was cancelled")
                if not line:
                    break
                total_bytes += len(line)
                if total_bytes > self.max_response_bytes or len(line) > 256 * 1024:
                    raise LocalInferenceError("local model runtime stream exceeds the size limit")
                text = line.decode("utf-8").strip()
                if not text or text.startswith(":"):
                    continue
                if not text.startswith("data:"):
                    continue
                data = text[5:].strip()
                if data == "[DONE]":
                    if not emitted_done:
                        emitted_done = True
                        yield self._stream_chunk(session, request, delta="", done=True, finish_reason="stop")
                    break
                try:
                    document = json.loads(data)
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise LocalInferenceError("local model runtime returned invalid stream JSON") from exc
                if not isinstance(document, Mapping):
                    raise LocalInferenceError("local model runtime returned a non-object stream item")
                choices = document.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
                    continue
                choice = choices[0]
                delta_document = choice.get("delta")
                delta = delta_document.get("content", "") if isinstance(delta_document, Mapping) else ""
                tool_calls = self._normalize_stream_tool_calls(
                    delta_document.get("tool_calls") if isinstance(delta_document, Mapping) else None
                )
                if not isinstance(delta, str) or len(delta) > 65536:
                    raise LocalInferenceError("local model runtime returned invalid stream content")
                finish_reason = choice.get("finish_reason")
                done = finish_reason is not None
                usage = self._normalize_usage(document.get("usage"))
                chunk = self._stream_chunk(
                    session,
                    request,
                    delta=delta,
                    done=done,
                    finish_reason=(str(finish_reason) if finish_reason is not None else None),
                    usage=usage,
                    tool_calls=tool_calls,
                )
                yield chunk
                if done:
                    emitted_done = True
                    break
            if not emitted_done:
                yield self._stream_chunk(session, request, delta="", done=True, finish_reason="stop")
        finally:
            self._stop_cancellation_watcher(watcher)
            response.close()

    @staticmethod
    def _normalize_usage(value: Any) -> dict[str, int] | None:
        if not isinstance(value, Mapping):
            return None
        required = {key: value.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        if not all(isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in required.values()):
            return None
        normalized = {key: int(item) for key, item in required.items()}
        for key in (
            "cpu_milliseconds", "gpu_milliseconds", "vram_byte_seconds",
            "network_bytes", "artifact_bytes", "external_cost_micros",
        ):
            item = value.get(key)
            if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                normalized[key] = int(item)
        return normalized

    @staticmethod
    def _normalize_stream_tool_calls(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 32:
            raise LocalInferenceError("local model runtime returned invalid stream tool calls")
        normalized: list[dict[str, Any]] = []
        for position, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise LocalInferenceError("local model runtime returned an invalid stream tool call")
            index = item.get("index", position)
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 31:
                raise LocalInferenceError("local model runtime returned an invalid stream tool index")
            call: dict[str, Any] = {"index": index}
            if item.get("id") is not None:
                if not isinstance(item["id"], str) or not 1 <= len(item["id"]) <= 160:
                    raise LocalInferenceError("local model runtime returned an invalid stream tool id")
                call["id"] = item["id"]
            if item.get("type") is not None:
                if item["type"] != "function":
                    raise LocalInferenceError("local model runtime returned an invalid stream tool type")
                call["type"] = "function"
            function = item.get("function")
            if function is not None:
                if not isinstance(function, Mapping):
                    raise LocalInferenceError("local model runtime returned an invalid stream tool function")
                normalized_function: dict[str, str] = {}
                for field, limit in (("name", 256), ("arguments", 131072)):
                    if function.get(field) is not None:
                        field_value = function[field]
                        if not isinstance(field_value, str) or len(field_value) > limit:
                            raise LocalInferenceError("local model runtime returned an invalid stream tool function")
                        normalized_function[field] = field_value
                call["function"] = normalized_function
            normalized.append(call)
        return normalized

    @staticmethod
    def _stream_chunk(
        session: SessionSnapshot,
        request: Mapping[str, Any],
        *,
        delta: str,
        done: bool,
        finish_reason: str | None,
        usage: Mapping[str, int] | None = None,
        tool_calls: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        chunk: dict[str, Any] = {
            "schema_version": 1,
            "session_id": str(request["session_id"]),
            "turn_id": str(request["turn_id"]),
            "lease_id": str(request["lease_id"]),
            "node_id": str(session.node_id),
            "model_id": str(request["model_id"]),
            "delta": delta,
            "done": done,
            "finish_reason": finish_reason,
        }
        if usage is not None:
            chunk["usage"] = dict(usage)
        if tool_calls:
            chunk["tool_calls"] = [dict(item) for item in tool_calls]
        return chunk
