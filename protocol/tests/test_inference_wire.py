from __future__ import annotations

import pytest
from protocol.inference_wire import InferenceContractError, assemble_inference_stream


def _chunk(**overrides):
    value = {
        "schema_version": 1,
        "session_id": "session-a",
        "turn_id": "turn-a",
        "lease_id": "lease-a",
        "node_id": "node-a",
        "model_id": "model-a",
        "delta": "",
        "done": False,
    }
    value.update(overrides)
    return value


def test_assemble_stream_reconstructs_text_and_tool_call_arguments() -> None:
    result = assemble_inference_stream([
        _chunk(delta="hello"),
        _chunk(tool_calls=[{
            "index": 0,
            "id": "call_1",
            "type": "function",
            "function": {"name": "read_status", "arguments": "{"},
        }]),
        _chunk(tool_calls=[{"index": 0, "function": {"arguments": "}"}}], done=True, finish_reason="tool_calls"),
    ])
    assert result["output"] == "hello"
    assert result["tool_calls"][0]["function"] == {
        "name": "read_status",
        "arguments": "{}",
    }


def test_assemble_stream_requires_terminal_chunk() -> None:
    with pytest.raises(InferenceContractError):
        assemble_inference_stream([_chunk(delta="partial")])
