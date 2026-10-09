import json
import unittest
from io import BytesIO

from services.mcp.platform.openai_agents import (
    OpenAIAgentsClient,
    OpenAIAgentsConfig,
    OpenAIAgentsProviderError,
)


class _Response:
    def __init__(self, body: bytes):
        self.body = BytesIO(body)

    def read(self, limit=-1):
        return self.body.read(limit)

    def readline(self):
        return self.body.readline()


class OpenAIAgentsProviderTests(unittest.TestCase):
    def test_provider_is_disabled_without_server_side_key(self):
        client = OpenAIAgentsClient(
            OpenAIAgentsConfig(base_url="https://api.openai.com"),
            environ={},
        )
        self.assertFalse(client.enabled)
        with self.assertRaisesRegex(OpenAIAgentsProviderError, "not configured"):
            client.create_session({"model": "gpt-test"}, "hello")

    def test_create_and_continue_use_agents_contract_and_idempotency(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout, json.loads(request.data.decode("utf-8"))))
            return _Response(b'{"session_id":"sess_1","status":"ready"}')

        client = OpenAIAgentsClient(
            OpenAIAgentsConfig(base_url="https://api.openai.com"),
            opener=opener,
            environ={"OPENAI_API_KEY": "server-secret"},
        )
        created = client.create_session(
            {"model": "gpt-test", "instructions": "Use safe tools."},
            "hello",
            environment={"type": "none"},
            idempotency_key="create-1",
        )
        continued = client.send_message("sess_1", "continue", idempotency_key="turn-1")

        self.assertEqual(created["session_id"], "sess_1")
        self.assertEqual(continued["status"], "ready")
        self.assertEqual(calls[0][0].full_url, "https://api.openai.com/v1/agents/sessions")
        self.assertEqual(calls[1][0].full_url, "https://api.openai.com/v1/agents/sessions/sess_1/events")
        self.assertEqual(calls[0][0].get_header("Openai-beta"), "agents=v1")
        self.assertEqual(calls[0][0].get_header("Authorization"), "Bearer server-secret")
        self.assertEqual(calls[0][0].get_header("Idempotency-key"), "create-1")
        self.assertEqual(calls[1][0].get_header("Idempotency-key"), "turn-1")
        self.assertEqual(calls[1][2]["events"][0]["type"], "agent.session.input.message")

    def test_stream_parser_handles_sse_events_and_done_marker(self):
        def opener(request, timeout):
            self.assertEqual(request.get_header("Accept"), "text/event-stream")
            return _Response(
                b'data: {"type":"agent.session.turn.started"}\n\n'
                b'data: {"type":"agent.session.turn.output_text.delta","delta":"hi"}\n\n'
                b'data: [DONE]\n\n'
            )

        client = OpenAIAgentsClient(
            OpenAIAgentsConfig(base_url="https://api.openai.com"),
            opener=opener,
            environ={"OPENAI_API_KEY": "server-secret"},
        )
        events = list(client.stream_events("sess_1"))
        self.assertEqual([event["type"] for event in events], [
            "agent.session.turn.started",
            "agent.session.turn.output_text.delta",
        ])

    def test_non_loopback_http_and_invalid_session_ids_fail_closed(self):
        with self.assertRaises(ValueError):
            OpenAIAgentsConfig(base_url="http://example.test")
        client = OpenAIAgentsClient(
            OpenAIAgentsConfig(base_url="https://api.openai.com"),
            environ={"OPENAI_API_KEY": "server-secret"},
        )
        with self.assertRaises(ValueError):
            client.retrieve_session("sess/escape")

    def test_streaming_requests_validate_idempotency_keys(self):
        client = OpenAIAgentsClient(
            OpenAIAgentsConfig(base_url="https://api.openai.com"),
            environ={"OPENAI_API_KEY": "server-secret"},
        )
        with self.assertRaisesRegex(ValueError, "invalid OpenAI Agents idempotency key"):
            client._stream_request("GET", "/v1/agents/sessions/sess_1/events", None, idempotency_key="bad/key")


if __name__ == "__main__":
    unittest.main()
