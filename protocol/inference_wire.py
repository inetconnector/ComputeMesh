"""Validation helpers for authenticated, lease-bound NodeOS inference."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .session_contracts import SessionMessageContractValidator


class InferenceContractError(ValueError):
    """Raised when an inference request or response violates the wire contract."""


_CONTRACTS = SessionMessageContractValidator()


def validate_inference_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InferenceContractError("inference request must be an object")
    value = dict(payload)
    try:
        _CONTRACTS.validate("InferenceRequest", value)
    except (KeyError, ValueError) as exc:
        raise InferenceContractError(str(exc)) from exc
    return value


def validate_inference_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InferenceContractError("inference response must be an object")
    value = dict(payload)
    try:
        _CONTRACTS.validate("InferenceResponse", value)
    except (KeyError, ValueError) as exc:
        raise InferenceContractError(str(exc)) from exc
    return value


def validate_inference_stream_chunk(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InferenceContractError("inference stream chunk must be an object")
    value = dict(payload)
    try:
        _CONTRACTS.validate("InferenceStreamChunk", value)
    except (KeyError, ValueError) as exc:
        raise InferenceContractError(str(exc)) from exc
    return value


def assemble_inference_stream(chunks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Assemble validated text and native tool-call deltas into one response.

    The result deliberately matches the provider-neutral caller shape used by
    ``AgentLoop``. Repeated argument fragments are concatenated in arrival
    order, while the wire-level binding fields are validated on every chunk.
    """
    output: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    usage: dict[str, int] | None = None
    saw_done = False
    binding: tuple[str, str, str, str, str] | None = None
    for raw in chunks:
        chunk = validate_inference_stream_chunk(raw)
        current_binding = tuple(
            str(chunk[field])
            for field in ("session_id", "turn_id", "lease_id", "node_id", "model_id")
        )
        if binding is None:
            binding = current_binding
        elif current_binding != binding:
            raise InferenceContractError("inference stream binding changed mid-stream")
        output.append(str(chunk.get("delta") or ""))
        if isinstance(chunk.get("usage"), Mapping):
            usage = dict(chunk["usage"])
        raw_calls = chunk.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise InferenceContractError("stream tool_calls must be an array")
        for item in raw_calls:
            index = int(item["index"])
            current = calls.setdefault(index, {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            })
            if item.get("id") is not None:
                current["id"] = str(item["id"])
            if item.get("type") is not None:
                current["type"] = "function"
            function = item.get("function")
            if isinstance(function, Mapping):
                if function.get("name") is not None:
                    current["function"]["name"] += str(function["name"])
                if function.get("arguments") is not None:
                    current["function"]["arguments"] += str(function["arguments"])
        if chunk.get("done") is True:
            saw_done = True
    if not saw_done:
        raise InferenceContractError("inference stream did not contain a final chunk")
    result: dict[str, Any] = {"output": "".join(output)}
    if calls:
        result["tool_calls"] = [calls[index] for index in sorted(calls)]
    if usage is not None:
        result["usage"] = usage
    return result
