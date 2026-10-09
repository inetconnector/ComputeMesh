from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from apps.node.inference_backend import LocalInferenceError, LocalOpenAIInferenceBackend
from protocol.node_session import NodeSessionState, SessionSnapshot


def _session() -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-a",
        state=NodeSessionState.READY,
        revision=4,
        protocol_major=1,
        protocol_minor=0,
        node_id="node-a",
        principal_id="provider-a",
        auth_method="ed25519_challenge_v1",
        credential_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        negotiated_capabilities=frozenset({"inference_v1"}),
        profile_revision=2,
        drain_reason=None,
        close_reason=None,
    )


class _Response:
    status = 200

    def __init__(self, document: dict[str, object]):
        self.document = document

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        raw = json.dumps(self.document).encode("utf-8")
        return raw[:limit]


class _BlockingResponse:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.closed = threading.Event()

    def read(self, limit: int = -1) -> bytes:
        self.started.set()
        self.closed.wait(5)
        raise OSError("response closed")

    def close(self) -> None:
        self.closed.set()

    def __enter__(self) -> "_BlockingResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class _StreamResponse:
    def __init__(self, lines: list[bytes]):
        self.lines = iter(lines)

    def readline(self) -> bytes:
        return next(self.lines, b"")

    def close(self) -> None:
        return None


def _request() -> dict[str, object]:
    return {
        "session_id": "session-a",
        "turn_id": "turn-a",
        "lease_id": "lease-a",
        "model_id": "model-a",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 32,
        "stream": False,
    }


def test_backend_posts_bounded_openai_shape_and_normalizes_response() -> None:
    backend = LocalOpenAIInferenceBackend("http://127.0.0.1:8080/v1/chat/completions", auth_token="local-only")
    response = _Response({
        "choices": [{"message": {"role": "assistant", "content": "hello back"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    })
    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=response) as open_url:
        result = backend(_session(), _request())
    sent = open_url.call_args.args[0]
    assert json.loads(sent.data.decode("utf-8")) == {
        "model": "model-a",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 32,
        "stream": False,
    }
    assert sent.headers["Authorization"] == "Bearer local-only"
    assert result["output"] == "hello back"
    assert result["usage"]["total_tokens"] == 6


def test_backend_forwards_agent_tool_schemas_when_present() -> None:
    backend = LocalOpenAIInferenceBackend("http://127.0.0.1:8080/v1/chat/completions")
    response = _Response({
        "choices": [{"message": {"role": "assistant", "content": "tool result"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })
    request = {**_request(), "tools": [{"type": "function", "function": {"name": "read_status"}}]}
    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=response) as open_url:
        backend(_session(), request)
    sent = json.loads(open_url.call_args.args[0].data.decode("utf-8"))
    assert sent["tools"][0]["function"]["name"] == "read_status"


def test_backend_preserves_native_tool_calls_from_local_runtime() -> None:
    backend = LocalOpenAIInferenceBackend("http://127.0.0.1:8080/v1/chat/completions")
    response = _Response({
        "choices": [{"message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_status", "arguments": "{}"},
            }],
        }}],
    })
    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=response):
        result = backend(_session(), _request())
    assert result["output"] == ""
    assert result["tool_calls"][0]["function"]["name"] == "read_status"


def test_backend_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError):
        LocalOpenAIInferenceBackend("http://10.0.0.2:8080/v1/chat/completions")


def test_backend_rejects_invalid_completion() -> None:
    backend = LocalOpenAIInferenceBackend("http://localhost:8080/v1/chat/completions")
    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=_Response({"choices": []})):
        with pytest.raises(LocalInferenceError):
            backend(_session(), _request())


def test_backend_stops_before_network_when_cancelled() -> None:
    backend = LocalOpenAIInferenceBackend("http://localhost:8080/v1/chat/completions")
    cancel_event = threading.Event()
    cancel_event.set()
    with patch("apps.node.inference_backend.urlrequest.urlopen") as open_url:
        with pytest.raises(LocalInferenceError, match="cancelled"):
            backend(_session(), _request(), cancel_event)
    open_url.assert_not_called()


def test_backend_closes_blocking_response_on_cancel() -> None:
    backend = LocalOpenAIInferenceBackend("http://localhost:8080/v1/chat/completions")
    cancel_event = threading.Event()
    response = _BlockingResponse()
    result: list[BaseException] = []

    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=response):
        thread = threading.Thread(
            target=lambda: _capture_error(result, backend, cancel_event),
            daemon=True,
        )
        thread.start()
        assert response.started.wait(1)
        cancel_event.set()
        thread.join(2)

    assert not thread.is_alive()
    assert response.closed.is_set()
    assert len(result) == 1
    assert isinstance(result[0], LocalInferenceError)
    assert "cancelled" in str(result[0])


def test_backend_invokes_deployment_cancel_hook_once() -> None:
    cancel_hook = threading.Event()
    backend = LocalOpenAIInferenceBackend(
        "http://localhost:8080/v1/chat/completions",
        on_cancel=cancel_hook.set,
    )
    cancel_event = threading.Event()
    response = _BlockingResponse()
    result: list[BaseException] = []

    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=response):
        thread = threading.Thread(
            target=lambda: _capture_error(result, backend, cancel_event),
            daemon=True,
        )
        thread.start()
        assert response.started.wait(1)
        cancel_event.set()
        thread.join(2)

    assert not thread.is_alive()
    assert response.closed.is_set()
    assert cancel_hook.is_set()
    assert len(result) == 1
    assert isinstance(result[0], LocalInferenceError)


def _capture_error(result: list[BaseException], backend: LocalOpenAIInferenceBackend, cancel_event: threading.Event) -> None:
    try:
        backend(_session(), _request(), cancel_event)
    except BaseException as exc:
        result.append(exc)


def test_backend_normalizes_sse_stream_and_emits_final_chunk() -> None:
    backend = LocalOpenAIInferenceBackend("http://localhost:8080/v1/chat/completions")
    lines = [
        b'data: {"choices":[{"delta":{"content":"hel"},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n',
    ]
    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=_StreamResponse(lines)):
        chunks = list(backend.stream(_session(), _request()))
    assert [chunk["delta"] for chunk in chunks] == ["hel", "lo"]
    assert chunks[-1]["done"] is True
    assert chunks[-1]["finish_reason"] == "stop"


def test_backend_stops_sse_stream_after_cancel_signal() -> None:
    backend = LocalOpenAIInferenceBackend("http://localhost:8080/v1/chat/completions")
    cancel_event = threading.Event()

    class CancellingResponse(_StreamResponse):
        def readline(self) -> bytes:
            line = super().readline()
            cancel_event.set()
            return line

    response = CancellingResponse([b'data: {"choices":[{"delta":{"content":"hel"},"finish_reason":null}]}\n\n'])
    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=response):
        with pytest.raises(LocalInferenceError, match="cancelled"):
            list(backend.stream(_session(), _request(), cancel_event))


def test_backend_preserves_streaming_native_tool_call_deltas() -> None:
    backend = LocalOpenAIInferenceBackend("http://localhost:8080/v1/chat/completions")
    lines = [
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"read_status","arguments":"{"}}]},"finish_reason":null}]}\n\n',
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"}"}}]},"finish_reason":"tool_calls"}]}\n\n',
    ]
    with patch("apps.node.inference_backend.urlrequest.urlopen", return_value=_StreamResponse(lines)):
        chunks = list(backend.stream(_session(), _request()))
    assert chunks[0]["tool_calls"][0]["function"]["name"] == "read_status"
    assert chunks[1]["tool_calls"][0]["function"]["arguments"] == "}"
