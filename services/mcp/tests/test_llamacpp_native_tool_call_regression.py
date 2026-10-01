"""Regression reproduction for llama.cpp native tool-call handling.

This test intentionally models the screenshot conversation and the OpenAI-compatible
shape emitted by llama.cpp/Qwen.  It verifies that native tool arguments survive
the gateway's compatibility conversion without double encoding.
"""

import json
from unittest.mock import patch

from services.gateway.inference_backend import OpenAICompatibleHTTPBackend
from services.mcp.agent_loop import _fallback_tool_calls
from services.mcp.tool_registry import ToolRegistry


class _FakeHTTPResponse:
    def __init__(self, body: dict):
        self._raw = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit: int):
        return self._raw


def test_screenshot_followup_preserves_llamacpp_tool_arguments_as_object():
    messages = [
        {"role": "user", "content": "Hallo"},
        {"role": "assistant", "content": "Guten Tag! Wie kann ich Ihnen heute helfen?"},
        {"role": "user", "content": "Geht die Antwort auch schneller"},
    ]

    # This is the native OpenAI-compatible tool_calls shape returned by llama.cpp.
    arguments = {
        "name": "some_tool",
        "inputs": {"text": "Geht die Antwort auch schneller"},
    }
    llama_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_screenshot_1",
                    "type": "function",
                    "function": {
                        "name": "execute_custom_tool",
                        # OpenAI-compatible APIs encode function.arguments as a JSON string.
                        "arguments": json.dumps(arguments),
                    },
                }],
            }
        }],
        "usage": {"prompt_tokens": 42, "completion_tokens": 12},
    }

    backend = OpenAICompatibleHTTPBackend(base_url="http://llamacpp.test")
    with patch(
        "services.gateway.inference_backend.request.urlopen",
        return_value=_FakeHTTPResponse(llama_response),
    ):
        result = backend.complete(
            model_id="qwen2.5-1.5b-instruct",
            messages=messages,
            tools=[{
                "type": "function",
                "function": {
                    "name": "execute_custom_tool",
                    "description": "Execute a stored custom tool.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "inputs": {"type": "object"},
                        },
                        "required": ["name"],
                    },
                },
            }],
        )

    # Exercise the exact fallback path used by AgentLoop after gateway conversion.
    registry = ToolRegistry()
    parsed_calls = _fallback_tool_calls(result.text, registry)

    assert len(parsed_calls) == 1
    raw_args = parsed_calls[0]["function"]["arguments"]
    decoded_args = json.loads(raw_args)

    # One JSON decode must recover the argument object expected by execute_tools_batch.
    assert isinstance(decoded_args, dict)
    assert decoded_args == arguments
