"""Authenticated request/response transport for NodeOS model execution."""
from __future__ import annotations

import hashlib
import inspect
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from protocol.inference_wire import (
    InferenceContractError,
    validate_inference_request,
    validate_inference_response,
    validate_inference_stream_chunk,
)
from protocol.node_session import NodeSessionState, SessionSnapshot
from services.orchestrator.persistent_control_channel import (
    PersistentNodeControlClient,
)


class InferenceTransportError(RuntimeError):
    """Raised when an authenticated NodeOS inference request cannot complete."""


InferenceEventSink = Callable[[str, Mapping[str, Any]], None]


def _require_text(value: Any, field: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise InferenceTransportError(f"{field} must be a non-empty bounded string")
    return value


def _accepts_cancel_token(handler: Callable[..., Any]) -> bool:
    try:
        parameters = inspect.signature(handler).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [
        parameter for parameter in parameters
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    return len(positional) >= 3 or any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters
    )


class AuthenticatedNodeInferenceClient:
    """Send only session-, lease- and model-bound requests over a live channel."""

    def __init__(
        self,
        control_client: PersistentNodeControlClient,
        *,
        required_capability: str = "inference_v1",
        required_stream_capability: str = "inference_stream_v1",
        timeout_seconds: float = 120.0,
        event_sink: InferenceEventSink | None = None,
        capacity_client: Any | None = None,
        capacity_ttl_seconds: int = 300,
        capacity_device_id: str = "default",
        capacity_memory_mb: int = 0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        self.control_client = control_client
        self.required_capability = _require_text(required_capability, "required_capability")
        self.required_stream_capability = _require_text(required_stream_capability, "required_stream_capability")
        self.timeout_seconds = timeout_seconds
        self.event_sink = event_sink
        if not 1 <= int(capacity_ttl_seconds) <= 3600:
            raise ValueError("capacity_ttl_seconds must be between 1 and 3600")
        if isinstance(capacity_memory_mb, bool) or int(capacity_memory_mb) < 0:
            raise ValueError("capacity_memory_mb must be non-negative")
        self.capacity_client = capacity_client if capacity_client is not None else control_client
        self.capacity_ttl_seconds = int(capacity_ttl_seconds)
        self.capacity_device_id = _require_text(capacity_device_id, "capacity_device_id", max_length=128)
        self.capacity_memory_mb = int(capacity_memory_mb)

    @staticmethod
    def request_id(*, session_id: str, turn_id: str, lease_id: str) -> str:
        """Return the stable bounded control-request ID for one inference call."""
        material = f"{session_id}\0{turn_id}\0{lease_id}".encode("utf-8")
        return f"inference-{hashlib.sha256(material).hexdigest()[:48]}"

    def cancel(self, *, node_id: str, request_id: str, reason: str = "cancelled") -> bool:
        """Cancel a currently pending inference request on its live node channel."""
        return self.control_client.cancel(node_id=node_id, request_id=request_id, reason=reason)

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink(event_type, dict(payload))
        except Exception:
            # Observability must never break model execution.
            return

    def _reserve_capacity(
        self,
        *,
        node_id: str,
        session_id: str,
        turn_id: str,
        lease_id: str,
        request_id: str,
    ) -> tuple[str, str, str] | None:
        reserve = getattr(self.capacity_client, "reserve_capacity", None)
        release = getattr(self.capacity_client, "release_capacity", None)
        if not callable(reserve) or not callable(release):
            return None
        session_for = getattr(self.capacity_client, "session_for", None)
        if callable(session_for):
            capacity_session = session_for(node_id)
            negotiated = getattr(capacity_session, "negotiated_capabilities", frozenset())
            if "capacity_reservation_v1" not in negotiated:
                # Older authenticated nodes may support inference without the
                # optional provider-local capacity protocol.
                return None
        job_material = f"{session_id}\0{turn_id}\0{lease_id}\0{request_id}".encode("utf-8")
        job_id = f"agent-{hashlib.sha256(job_material).hexdigest()[:48]}"
        response = reserve(
            node_id=node_id,
            job_id=job_id,
            lease_id=lease_id,
            ttl_seconds=self.capacity_ttl_seconds,
            device_id=self.capacity_device_id,
            memory_mb=self.capacity_memory_mb,
            timeout_seconds=self.timeout_seconds,
        )
        if not isinstance(response, Mapping):
            raise InferenceTransportError("provider capacity reservation returned an invalid response")
        if (
            response.get("node_id") != node_id
            or response.get("job_id") != job_id
            or response.get("lease_id") != lease_id
        ):
            raise InferenceTransportError("provider capacity reservation binding mismatch")
        return job_id, node_id, lease_id

    def _release_capacity(self, handle: tuple[str, str, str] | None) -> None:
        if handle is None:
            return
        job_id, node_id, lease_id = handle
        release = getattr(self.capacity_client, "release_capacity", None)
        if not callable(release):
            return
        try:
            release(node_id=node_id, job_id=job_id, lease_id=lease_id, timeout_seconds=self.timeout_seconds)
        except Exception:
            # Provider TTLs are the final recovery boundary; a release failure
            # must not hide the already verified model result.
            return

    def request(
        self,
        *,
        node_id: str,
        session_id: str,
        turn_id: str,
        lease_id: str,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        request_id: str | None = None,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        node_id = _require_text(node_id, "node_id", max_length=160)
        session_id = _require_text(session_id, "session_id", max_length=160)
        turn_id = _require_text(turn_id, "turn_id", max_length=160)
        lease_id = _require_text(lease_id, "lease_id", max_length=160)
        model_id = _require_text(model_id, "model_id")
        session = self.control_client.session_for(node_id)
        self._check_session(session, node_id=node_id, session_id=session_id)
        event = {
            "node_id": node_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "lease_id": lease_id,
            "model_id": model_id,
        }
        self._emit("mesh.inference.started", event)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "session_id": session_id,
            "turn_id": turn_id,
            "lease_id": lease_id,
            "model_id": model_id,
            "messages": [dict(message) for message in messages],
            "max_tokens": max_tokens,
            "stream": False,
        }
        control_request_id = request_id or self.request_id(session_id=session_id, turn_id=turn_id, lease_id=lease_id)
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = [dict(tool) for tool in tools]
        capacity_handle: tuple[str, str, str] | None = None
        try:
            request = validate_inference_request(payload)
            capacity_handle = self._reserve_capacity(
                node_id=node_id,
                session_id=session_id,
                turn_id=turn_id,
                lease_id=lease_id,
                request_id=control_request_id,
            )
            cancel_stop, cancel_thread = self._start_cancel_watcher(
                cancel_event,
                node_id=node_id,
                request_id=control_request_id,
            )
            response = self.control_client.request(
                node_id=node_id,
                message_type="InferenceRequest",
                payload=request,
                timeout_seconds=self.timeout_seconds,
                request_id=control_request_id,
            )
            cancel_stop.set()
            cancel_thread.join(timeout=0.2)
            result = validate_inference_response(response)
            self._check_response(result, node_id=node_id, session_id=session_id, turn_id=turn_id, lease_id=lease_id, model_id=model_id)
            self._emit("mesh.inference.completed", {**event, "usage": dict(result.get("usage") or {})})
            return result
        except (InferenceContractError, ValueError, TypeError) as exc:
            self._emit("mesh.inference.failed", {**event, "error_type": type(exc).__name__})
            raise InferenceTransportError(str(exc)) from exc
        except Exception as exc:
            if "cancel_stop" in locals():
                cancel_stop.set()
                cancel_thread.join(timeout=0.2)
            self._emit("mesh.inference.failed", {**event, "error_type": type(exc).__name__})
            raise
        finally:
            self._release_capacity(capacity_handle)

    def _check_session(self, session: SessionSnapshot, *, node_id: str, session_id: str) -> None:
        if session.node_id != node_id or session.session_id != session_id:
            raise InferenceTransportError("inference session binding mismatch")
        if session.state is not NodeSessionState.READY:
            raise InferenceTransportError("node session is not ready for inference")
        if session.credential_expires_at <= datetime.now(timezone.utc):
            raise InferenceTransportError("node session credential has expired")
        if self.required_capability not in session.negotiated_capabilities:
            raise InferenceTransportError("node session lacks the required inference capability")

    def stream(
        self,
        *,
        node_id: str,
        session_id: str,
        turn_id: str,
        lease_id: str,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
        request_id: str | None = None,
        cancel_event: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        node_id = _require_text(node_id, "node_id", max_length=160)
        session_id = _require_text(session_id, "session_id", max_length=160)
        turn_id = _require_text(turn_id, "turn_id", max_length=160)
        lease_id = _require_text(lease_id, "lease_id", max_length=160)
        model_id = _require_text(model_id, "model_id")
        session = self.control_client.session_for(node_id)
        self._check_session(session, node_id=node_id, session_id=session_id)
        if self.required_stream_capability not in session.negotiated_capabilities:
            raise InferenceTransportError("node session lacks the required inference streaming capability")
        event = {
            "node_id": node_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "lease_id": lease_id,
            "model_id": model_id,
        }
        self._emit("mesh.inference.stream.started", event)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "session_id": session_id,
            "turn_id": turn_id,
            "lease_id": lease_id,
            "model_id": model_id,
            "messages": [dict(message) for message in messages],
            "max_tokens": max_tokens,
            "stream": True,
        }
        control_request_id = request_id or self.request_id(session_id=session_id, turn_id=turn_id, lease_id=lease_id)
        if temperature is not None:
            payload["temperature"] = temperature
        capacity_handle: tuple[str, str, str] | None = None
        try:
            request = validate_inference_request(payload)
            capacity_handle = self._reserve_capacity(
                node_id=node_id,
                session_id=session_id,
                turn_id=turn_id,
                lease_id=lease_id,
                request_id=control_request_id,
            )
            cancel_stop, cancel_thread = self._start_cancel_watcher(
                cancel_event,
                node_id=node_id,
                request_id=control_request_id,
            )
            chunks = self.control_client.request_stream(
                node_id=node_id,
                message_type="InferenceRequest",
                payload=request,
                timeout_seconds=self.timeout_seconds,
                request_id=control_request_id,
            )
        except (InferenceContractError, ValueError, TypeError) as exc:
            if "cancel_stop" in locals():
                cancel_stop.set()
                cancel_thread.join(timeout=0.2)
            self._release_capacity(capacity_handle)
            self._emit("mesh.inference.stream.failed", {**event, "error_type": type(exc).__name__})
            raise InferenceTransportError(str(exc)) from exc
        except Exception as exc:
            if "cancel_stop" in locals():
                cancel_stop.set()
                cancel_thread.join(timeout=0.2)
            self._release_capacity(capacity_handle)
            self._emit("mesh.inference.stream.failed", {**event, "error_type": type(exc).__name__})
            raise

        def receive() -> Iterator[dict[str, Any]]:
            chunk_count = 0
            character_count = 0
            digest = hashlib.sha256()
            try:
                for raw_chunk in chunks:
                    if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
                        raise InferenceTransportError("inference stream was cancelled")
                    chunk = validate_inference_stream_chunk(raw_chunk)
                    self._check_stream_chunk(
                        chunk,
                        node_id=node_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        lease_id=lease_id,
                        model_id=model_id,
                    )
                    chunk_count += 1
                    delta = str(chunk.get("delta") or "")
                    character_count += len(delta)
                    digest.update(delta.encode("utf-8"))
                    self._emit("mesh.inference.stream.chunk", {
                        **event,
                        "chunk_index": chunk_count,
                        "delta_characters": len(delta),
                        "done": bool(chunk.get("done")),
                    })
                    if chunk.get("done") is True:
                        self._emit("mesh.inference.stream.completed", {
                            **event,
                            "chunk_count": chunk_count,
                            "character_count": character_count,
                            "output_digest": digest.hexdigest(),
                            "usage": dict(chunk.get("usage") or {}),
                        })
                    yield chunk
            except (InferenceContractError, ValueError, TypeError) as exc:
                self._emit("mesh.inference.stream.failed", {**event, "error_type": type(exc).__name__})
                raise InferenceTransportError(str(exc)) from exc
            except Exception as exc:
                self._emit("mesh.inference.stream.failed", {**event, "error_type": type(exc).__name__})
                raise
            finally:
                cancel_stop.set()
                cancel_thread.join(timeout=0.2)
                self._release_capacity(capacity_handle)

        return receive()

    def _start_cancel_watcher(
        self,
        cancel_event: Any | None,
        *,
        node_id: str,
        request_id: str,
    ) -> tuple[threading.Event, threading.Thread]:
        stop = threading.Event()

        def watch() -> None:
            if cancel_event is None:
                stop.wait()
                return
            wait = getattr(cancel_event, "wait", None)
            triggered = bool(wait()) if callable(wait) else bool(getattr(cancel_event, "is_set", lambda: False)())
            if triggered and not stop.is_set():
                try:
                    self.cancel(node_id=node_id, request_id=request_id, reason="agent_turn_cancelled")
                except Exception:
                    pass

        thread = threading.Thread(target=watch, name=f"inference-cancel-{request_id}", daemon=True)
        thread.start()
        return stop, thread

    @staticmethod
    def _check_response(
        response: Mapping[str, Any],
        *,
        node_id: str,
        session_id: str,
        turn_id: str,
        lease_id: str,
        model_id: str,
    ) -> None:
        expected = {
            "node_id": node_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "lease_id": lease_id,
            "model_id": model_id,
        }
        for field, value in expected.items():
            if response.get(field) != value:
                raise InferenceTransportError(f"inference response {field} binding mismatch")

    @staticmethod
    def _check_stream_chunk(
        chunk: Mapping[str, Any],
        *,
        node_id: str,
        session_id: str,
        turn_id: str,
        lease_id: str,
        model_id: str,
    ) -> None:
        expected = {
            "node_id": node_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "lease_id": lease_id,
            "model_id": model_id,
        }
        for field, value in expected.items():
            if chunk.get(field) != value:
                raise InferenceTransportError(f"inference stream {field} binding mismatch")


class AuthenticatedNodeModelExecutor:
    """Dispatcher adapter that turns a lease into one authenticated wire call."""

    def __init__(self, client: AuthenticatedNodeInferenceClient) -> None:
        self.client = client

    def execute_dispatch(
        self,
        node: Any,
        payload: Mapping[str, Any],
        *,
        session_id: str,
        turn_id: str,
        model_id: str,
        lease: Any,
        cancel_event: Any | None = None,
    ) -> Mapping[str, Any]:
        messages = payload.get("messages")
        if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
            raise InferenceTransportError("model dispatch payload requires a messages array")
        return self.client.request(
            node_id=str(node.node_id),
            session_id=session_id,
            turn_id=turn_id,
            lease_id=str(lease.lease_id),
            model_id=model_id,
            messages=messages,
            max_tokens=int(payload.get("max_tokens", 1024)),
            temperature=(float(payload["temperature"]) if "temperature" in payload else None),
            tools=(payload.get("tools") if isinstance(payload.get("tools"), Sequence) and not isinstance(payload.get("tools"), (str, bytes)) else None),
            request_id=self.client.request_id(session_id=session_id, turn_id=turn_id, lease_id=str(lease.lease_id)),
            cancel_event=cancel_event,
        )


def make_inference_request_handler(
    executor: Callable[..., Mapping[str, Any]],
    *,
    required_capability: str = "inference_v1",
) -> Callable[[str, dict[str, Any], SessionSnapshot], dict[str, Any]]:
    """Adapt a local NodeOS model runtime to ``ProviderPersistentClient``.

    The executor receives already validated, bounded data. It never receives
    credentials or an arbitrary shell request.
    """

    required_capability = _require_text(required_capability, "required_capability")

    def handle(
        message_type: str,
        payload: dict[str, Any],
        session: SessionSnapshot,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        if message_type != "InferenceRequest":
            raise InferenceTransportError(f"unsupported provider request {message_type}")
        if required_capability not in session.negotiated_capabilities:
            raise InferenceTransportError("provider session lacks the required inference capability")
        request = validate_inference_request(payload)
        if request["session_id"] != session.session_id:
            raise InferenceTransportError("inference request session binding mismatch")
        if cancel_event is not None and _accepts_cancel_token(executor):
            result = executor(session, request, cancel_event)
        else:
            result = executor(session, request)
        response = validate_inference_response(result)
        if response["session_id"] != session.session_id or response["node_id"] != session.node_id:
            raise InferenceTransportError("provider inference response binding mismatch")
        if response["model_id"] != request["model_id"] or response["turn_id"] != request["turn_id"] or response["lease_id"] != request["lease_id"]:
            raise InferenceTransportError("provider inference response request binding mismatch")
        return response

    return handle


def make_inference_stream_handler(
    executor: Callable[..., Iterable[Mapping[str, Any]]],
    *,
    required_capability: str = "inference_stream_v1",
) -> Callable[[str, dict[str, Any], SessionSnapshot], Iterator[Mapping[str, Any]]]:
    """Adapt a provider streaming generator to the validated channel contract."""

    required_capability = _require_text(required_capability, "required_capability")

    def handle(
        message_type: str,
        payload: dict[str, Any],
        session: SessionSnapshot,
        cancel_event: Any | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        if message_type != "InferenceRequest":
            raise InferenceTransportError(f"unsupported provider stream request {message_type}")
        if required_capability not in session.negotiated_capabilities:
            raise InferenceTransportError("provider session lacks the required inference streaming capability")
        request = validate_inference_request(payload)
        if request["stream"] is not True or request["session_id"] != session.session_id:
            raise InferenceTransportError("inference stream request binding mismatch")
        chunks = executor(session, request, cancel_event) if cancel_event is not None and _accepts_cancel_token(executor) else executor(session, request)
        for raw_chunk in chunks:
            if cancel_event is not None and cancel_event.is_set():
                raise InferenceTransportError("inference stream was cancelled")
            chunk = validate_inference_stream_chunk(raw_chunk)
            if chunk["session_id"] != session.session_id or chunk["node_id"] != session.node_id:
                raise InferenceTransportError("provider inference stream identity binding mismatch")
            if chunk["model_id"] != request["model_id"] or chunk["turn_id"] != request["turn_id"] or chunk["lease_id"] != request["lease_id"]:
                raise InferenceTransportError("provider inference stream request binding mismatch")
            yield chunk

    return handle
