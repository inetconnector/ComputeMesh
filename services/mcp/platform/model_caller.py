"""Provider-neutral model caller adapter for the durable agent worker."""
from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Callable, Mapping, Protocol

from .node_routing import NodeRouteRequirement


class ModelCallerError(RuntimeError):
    """Raised when a backend result cannot satisfy the agent caller contract."""


_PROVENANCE_ID_LIMIT = 160
_PROVENANCE_LIST_LIMIT = 32


@dataclass(frozen=True)
class _MeshExecutionEvidence:
    """Private callback payload for deployment-owned mesh settlement."""

    execution_job_id: str
    prompt_tokens: int
    completion_tokens: int
    provider_shares: tuple[tuple[str, float], ...]


def _bounded_provenance_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if 1 <= len(value) <= _PROVENANCE_ID_LIMIT else None


def _execution_provenance(
    *,
    execution_job_id: Any = None,
    execution_node_ids: Any = (),
) -> dict[str, list[str]]:
    """Expose only bounded opaque execution identifiers to the public runtime."""
    result: dict[str, list[str]] = {}
    job_id = _bounded_provenance_id(execution_job_id)
    if job_id is not None:
        result["execution_job_ids"] = [job_id]
    if isinstance(execution_node_ids, str):
        execution_node_ids = (execution_node_ids,)
    node_ids: list[str] = []
    if isinstance(execution_node_ids, (list, tuple, set, frozenset)):
        for value in execution_node_ids:
            node_id = _bounded_provenance_id(value)
            if node_id is not None and node_id not in node_ids:
                node_ids.append(node_id)
            if len(node_ids) >= _PROVENANCE_LIST_LIMIT:
                break
    if node_ids:
        result["execution_node_ids"] = node_ids
    return result


class CompletionBackend(Protocol):
    def complete(self, **kwargs: Any) -> Any:
        """Return a backend result with text and token usage fields."""


@dataclass(frozen=True)
class BackendModelCaller:
    """Adapt one existing ComputeMesh inference backend to ``AgentLoop``.

    The backend instance and model ID are fixed when the caller is created.
    Optional keyword arguments are passed only when the backend signature
    advertises them (or accepts ``**kwargs``), so an orchestrated backend that
    intentionally exposes only its verified text contract is not bypassed.
    """

    backend: CompletionBackend
    model_id: str
    max_tokens: int | None = None
    response_format: Mapping[str, Any] | None = None
    result_observer: Callable[[Any], None] | None = None

    def __post_init__(self) -> None:
        model = str(self.model_id or "").strip()
        if not 1 <= len(model) <= 256:
            raise ValueError("model_id must be between 1 and 256 characters")
        object.__setattr__(self, "model_id", model)
        if self.max_tokens is not None:
            try:
                normalized_max_tokens = int(self.max_tokens)
            except (TypeError, ValueError) as exc:
                raise ValueError("max_tokens is outside the supported range") from exc
            if not 1 <= normalized_max_tokens <= 1_000_000:
                raise ValueError("max_tokens is outside the supported range")
            object.__setattr__(self, "max_tokens", normalized_max_tokens)
        if not callable(getattr(self.backend, "complete", None)):
            raise TypeError("backend must provide complete()")
        if self.result_observer is not None and not callable(self.result_observer):
            raise TypeError("result_observer must be callable")

    @staticmethod
    def _accepted_keywords(method: Callable[..., Any]) -> tuple[set[str], bool]:
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return set(), False
        accepted = {
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        }
        variadic = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        return accepted, variadic

    def _backend_kwargs(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        method = self.backend.complete
        accepted, variadic = self._accepted_keywords(method)
        values: dict[str, Any] = {
            "model_id": self.model_id,
            "messages": [dict(message) for message in messages],
        }
        optional: dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "tools": tools or None,
            "response_format": dict(self.response_format) if self.response_format is not None else None,
        }
        for key, value in optional.items():
            if value is not None and (variadic or key in accepted):
                values[key] = value
        return values

    @staticmethod
    def _cancelled(cancel_event: Any | None) -> bool:
        return cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)())

    def __call__(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        if not isinstance(messages, list) or not isinstance(tools, list):
            raise ModelCallerError("agent model caller expects message and tool lists")
        if self._cancelled(cancel_event):
            raise ModelCallerError("inference backend call was cancelled")
        backend_kwargs = self._backend_kwargs(messages, tools)
        accepted, variadic = self._accepted_keywords(self.backend.complete)
        if cancel_event is not None and (variadic or "cancel_event" in accepted):
            backend_kwargs["cancel_event"] = cancel_event
        try:
            result = self.backend.complete(**backend_kwargs)
        except Exception as exc:
            raise ModelCallerError("inference backend failed for agent turn") from exc
        if self._cancelled(cancel_event):
            raise ModelCallerError("inference backend call was cancelled")
        text = getattr(result, "text", None)
        prompt_tokens = getattr(result, "prompt_tokens", None)
        completion_tokens = getattr(result, "completion_tokens", None)
        if not isinstance(text, str) or not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
            raise ModelCallerError("inference backend returned an invalid agent completion")
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ModelCallerError("inference backend returned negative token usage")
        if self.result_observer is not None:
            try:
                self.result_observer(result)
            except Exception as exc:
                raise ModelCallerError("inference result observer failed") from exc
        resource_usage: dict[str, int] = {}
        for field in (
            "cpu_milliseconds",
            "gpu_milliseconds",
            "vram_byte_seconds",
            "network_bytes",
            "artifact_bytes",
            "external_cost_micros",
        ):
            value = getattr(result, field, None)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                resource_usage[field] = int(value)
        usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
        usage.update(resource_usage)
        response: dict[str, Any] = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": text,
                },
            }],
            "usage": usage,
        }
        provenance = _execution_provenance(
            execution_job_id=getattr(result, "execution_job_id", None),
            execution_node_ids=getattr(result, "execution_node_ids", ()),
        )
        if provenance:
            response["provenance"] = provenance
        return response


def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize AgentLoop messages to the bounded NodeOS wire contract."""
    result: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ModelCallerError("mesh agent message has an unsupported role")
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, Mapping):
                    value = item.get("text") or item.get("content")
                    if value is not None:
                        parts.append(str(value))
            text = "\n".join(parts)
        elif content is None:
            text = ""
        else:
            text = json.dumps(content, ensure_ascii=False, separators=(",", ":"), default=str)
        if not text:
            text = "(no textual content)"
        if len(text) > 1_048_576:
            raise ModelCallerError("mesh agent message exceeds the wire size limit")
        normalized: dict[str, Any] = {"role": role, "content": text}
        for field, max_length in (("name", 256), ("tool_call_id", 160)):
            value = message.get(field)
            if value is not None:
                if not isinstance(value, str) or not 1 <= len(value) <= max_length:
                    raise ModelCallerError(f"mesh agent message has an invalid {field}")
                normalized[field] = value
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls is not None:
            if not isinstance(raw_tool_calls, list) or len(raw_tool_calls) > 32:
                raise ModelCallerError("mesh agent message has invalid tool calls")
            tool_calls: list[dict[str, Any]] = []
            for item in raw_tool_calls:
                if not isinstance(item, Mapping) or item.get("type") != "function":
                    raise ModelCallerError("mesh agent message has an invalid tool call")
                function = item.get("function")
                if not isinstance(function, Mapping):
                    raise ModelCallerError("mesh agent message has an invalid tool function")
                call_id = item.get("id")
                name = function.get("name")
                arguments = function.get("arguments")
                if (
                    not isinstance(call_id, str) or not 1 <= len(call_id) <= 160
                    or not isinstance(name, str) or not 1 <= len(name) <= 256
                    or not isinstance(arguments, str) or len(arguments) > 131072
                ):
                    raise ModelCallerError("mesh agent message has an invalid tool function")
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                })
            normalized["tool_calls"] = tool_calls
        result.append(normalized)
    if not result:
        raise ModelCallerError("mesh agent requires at least one message")
    return result


@dataclass
class MeshDispatchModelCaller:
    """Adapt the lease-bound NodeOS dispatcher to the AgentLoop caller API."""

    dispatcher: Any
    session_id: str
    turn_id: str
    model_id: str
    requirement: NodeRouteRequirement | None = None
    max_tokens: int = 1024
    capacity_limit: int = 1
    requested_slots: int = 1
    lease_ttl_seconds: int = 300
    result_observer: Callable[[Any], None] | None = None
    _call_index: int = dataclass_field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("session_id", self.session_id, 160),
            ("turn_id", self.turn_id, 160),
            ("model_id", self.model_id, 256),
        ):
            clean = str(value or "").strip()
            if not 1 <= len(clean) <= limit:
                raise ValueError(f"{name} is required and bounded")
            setattr(self, name, clean)
        if not 1 <= int(self.max_tokens) <= 131_072:
            raise ValueError("max_tokens is outside the supported range")
        if not 1 <= int(self.capacity_limit) <= 1024 or not 1 <= int(self.requested_slots) <= int(self.capacity_limit):
            raise ValueError("dispatcher capacity values are invalid")
        if not 1 <= int(self.lease_ttl_seconds) <= 3600:
            raise ValueError("lease_ttl_seconds is outside the supported range")
        if not callable(getattr(self.dispatcher, "dispatch", None)):
            raise TypeError("dispatcher must provide dispatch()")
        if self.result_observer is not None and not callable(self.result_observer):
            raise TypeError("result_observer must be callable")

    def __call__(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
            raise ModelCallerError("mesh model dispatch was cancelled")
        self._call_index += 1
        payload: dict[str, Any] = {
            "messages": _wire_messages(messages),
            "max_tokens": int(self.max_tokens),
        }
        if tools:
            payload["tools"] = [dict(tool) for tool in tools[:128]]
        requirement = self.requirement or NodeRouteRequirement(
            model_id=self.model_id,
            required_capabilities=frozenset({"inference_v1"}),
        )
        try:
            dispatched = self.dispatcher.dispatch(
                session_id=self.session_id,
                turn_id=self.turn_id,
                model_id=self.model_id,
                requirement=requirement,
                payload=payload,
                idempotency_key=f"agent_call:{self.session_id}:{self.turn_id}:{self._call_index}",
                capacity_limit=int(self.capacity_limit),
                requested_slots=int(self.requested_slots),
                ttl_seconds=int(self.lease_ttl_seconds),
                cancel_event=cancel_event,
            )
        except Exception as exc:
            raise ModelCallerError("mesh model dispatch failed") from exc
        if cancel_event is not None and bool(getattr(cancel_event, "is_set", lambda: False)()):
            raise ModelCallerError("mesh model dispatch was cancelled")
        response = getattr(dispatched, "response", dispatched)
        if not isinstance(response, Mapping):
            raise ModelCallerError("mesh model dispatch returned an invalid response")
        output = response.get("output")
        if not isinstance(output, str) or len(output) > 4 * 1024 * 1024:
            raise ModelCallerError("mesh model dispatch returned invalid output")
        raw_tool_calls = response.get("tool_calls")
        tool_calls: list[dict[str, Any]] = []
        if raw_tool_calls is not None:
            if not isinstance(raw_tool_calls, list) or len(raw_tool_calls) > 32:
                raise ModelCallerError("mesh model dispatch returned invalid tool calls")
            for item in raw_tool_calls:
                if not isinstance(item, Mapping) or item.get("type") != "function":
                    raise ModelCallerError("mesh model dispatch returned an invalid tool call")
                function = item.get("function")
                if not isinstance(function, Mapping):
                    raise ModelCallerError("mesh model dispatch returned an invalid tool function")
                call_id = item.get("id")
                name = function.get("name")
                arguments = function.get("arguments")
                if (
                    not isinstance(call_id, str) or not 1 <= len(call_id) <= 160
                    or not isinstance(name, str) or not 1 <= len(name) <= 256
                    or not isinstance(arguments, str) or len(arguments) > 131072
                ):
                    raise ModelCallerError("mesh model dispatch returned an invalid tool function")
                tool_calls.append({
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                })
        usage = response.get("usage")
        prompt_tokens = 0
        completion_tokens = 0
        if isinstance(usage, Mapping):
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        if (
            isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0
            or isinstance(completion_tokens, bool) or not isinstance(completion_tokens, int) or completion_tokens < 0
        ):
            raise ModelCallerError("mesh model dispatch returned invalid usage")
        usage_mapping = usage if isinstance(usage, Mapping) else {}
        resource_usage = {
            field: int(usage_mapping[field])
            for field in (
                "cpu_milliseconds",
                "gpu_milliseconds",
                "vram_byte_seconds",
                "network_bytes",
                "artifact_bytes",
                "external_cost_micros",
            )
            if isinstance(usage_mapping.get(field), int)
            and not isinstance(usage_mapping.get(field), bool)
            and int(usage_mapping[field]) >= 0
        }
        message: dict[str, Any] = {"role": "assistant", "content": output}
        if tool_calls:
            message["tool_calls"] = tool_calls
        result: dict[str, Any] = {
            "choices": [{"message": message}],
            "usage": {
                "prompt_tokens": int(prompt_tokens),
                "completion_tokens": int(completion_tokens),
                **resource_usage,
            },
        }
        raw_execution_node_ids = response.get("execution_node_ids", ())
        if isinstance(raw_execution_node_ids, str):
            raw_execution_node_ids = (raw_execution_node_ids,)
        elif not isinstance(raw_execution_node_ids, (list, tuple, set, frozenset)):
            raw_execution_node_ids = ()
        provenance = _execution_provenance(
            execution_job_id=response.get("execution_job_id") or getattr(dispatched, "execution_job_id", None),
            execution_node_ids=(
                list(raw_execution_node_ids)
                + ([response.get("node_id")] if response.get("node_id") is not None else [])
                + ([getattr(dispatched, "node_id", None)] if getattr(dispatched, "node_id", None) is not None else [])
            ),
        )
        if provenance:
            result["provenance"] = provenance
        if self.result_observer is not None:
            selected_node_id = str(
                getattr(dispatched, "node_id", None)
                or response.get("node_id")
                or ""
            ).strip()
            if not selected_node_id:
                raise ModelCallerError("mesh settlement evidence is missing the selected node")
            material = (
                f"{self.session_id}\0{self.turn_id}\0{self._call_index}\0"
                f"{selected_node_id}\0{getattr(getattr(dispatched, 'lease', None), 'lease_id', '')}"
            ).encode("utf-8")
            execution_job_id = f"mesh-agent-{hashlib.sha256(material).hexdigest()[:48]}"
            self.result_observer(
                _MeshExecutionEvidence(
                    execution_job_id=execution_job_id,
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                    provider_shares=((selected_node_id, 1.0),),
                )
            )
        return result


def make_backend_model_caller(
    backend: CompletionBackend,
    *,
    model_id: str,
    max_tokens: int | None = None,
    response_format: Mapping[str, Any] | None = None,
    result_observer: Callable[[Any], None] | None = None,
) -> Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]:
    """Create an ``AgentLoop`` caller bound to one existing backend/model."""
    return BackendModelCaller(
        backend,
        model_id=model_id,
        max_tokens=max_tokens,
        response_format=response_format,
        result_observer=result_observer,
    )
