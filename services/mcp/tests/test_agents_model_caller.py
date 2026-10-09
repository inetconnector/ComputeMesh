"""Tests for the durable agent adapter over existing inference backends."""
from __future__ import annotations

import threading
import unittest

from services.gateway.inference_backend import BackendResult, SyntheticInferenceBackend
from services.mcp.platform.model_caller import (
    BackendModelCaller,
    MeshDispatchModelCaller,
    ModelCallerError,
    make_backend_model_caller,
)


class _ToolBackend:
    def __init__(self) -> None:
        self.calls = []

    def complete(self, *, model_id, messages, max_tokens=None, tools=None, response_format=None):
        self.calls.append({
            "model_id": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "tools": tools,
            "response_format": response_format,
        })
        return BackendResult("answer", 4, 6, execution_job_id="job-1", execution_node_ids=("node-a", "node-b"))


class _LegacyBackend:
    def __init__(self) -> None:
        self.calls = []

    def complete(self, *, model_id, messages):
        self.calls.append((model_id, messages))
        return BackendResult("legacy", 1, 2)


class _InvalidBackend:
    def complete(self, **kwargs):
        return {"text": "not a BackendResult"}


class _ResourceBackend:
    def complete(self, **kwargs):
        return type("BackendResultWithResources", (), {
            "text": "metered",
            "prompt_tokens": 2,
            "completion_tokens": 3,
            "gpu_milliseconds": 11,
            "vram_byte_seconds": 13,
            "network_bytes": 17,
            "external_cost_micros": 19,
        })()


class _CancellableBackend:
    def __init__(self) -> None:
        self.started = threading.Event()

    def complete(self, *, model_id, messages, cancel_event):
        self.started.set()
        if not cancel_event.wait(1):
            raise AssertionError("cancel event was not signalled")
        raise RuntimeError("cancelled")


class _DispatchResult:
    def __init__(self, response, *, node_id="node-mesh", lease_id="lease-mesh"):
        self.response = response
        self.node_id = node_id
        self.lease = type("Lease", (), {"lease_id": lease_id})()


class _Dispatcher:
    def __init__(self) -> None:
        self.calls = []

    def dispatch(self, **kwargs):
        self.calls.append(kwargs)
        return _DispatchResult({
            "output": "mesh answer",
            "execution_job_id": "mesh-job-1",
            "execution_node_ids": ["node-mesh"],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        })


class _ToolDispatcher(_Dispatcher):
    def dispatch(self, **kwargs):
        self.calls.append(kwargs)
        return _DispatchResult({
            "output": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_status", "arguments": "{}"},
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        })


class TestBackendModelCaller(unittest.TestCase):
    def test_forwards_cancel_event_to_backend_and_fails_closed(self):
        backend = _CancellableBackend()
        caller = BackendModelCaller(backend, "cancellable-model")
        cancel_event = threading.Event()
        result: list[BaseException] = []

        def run() -> None:
            try:
                caller([{"role": "user", "content": "hello"}], [], cancel_event=cancel_event)
            except BaseException as exc:
                result.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(backend.started.wait(1))
        cancel_event.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], ModelCallerError)

    def test_notifies_private_observer_before_public_conversion(self):
        backend = _ToolBackend()
        observed = []
        caller = BackendModelCaller(backend, "demo-model", result_observer=observed.append)
        caller([{"role": "user", "content": "hello"}], [])
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].execution_job_id, "job-1")

    def test_observer_failure_fails_closed(self):
        caller = BackendModelCaller(
            _ToolBackend(),
            "demo-model",
            result_observer=lambda _result: (_ for _ in ()).throw(RuntimeError("observer down")),
        )
        with self.assertRaises(ModelCallerError):
            caller([{"role": "user", "content": "hello"}], [])

    def test_passes_supported_tools_and_converts_usage(self):
        backend = _ToolBackend()
        caller = BackendModelCaller(backend, "demo-model", max_tokens=32, response_format={"type": "text"})
        result = caller(
            [{"role": "user", "content": "hello"}],
            [{"type": "function", "function": {"name": "read_tool"}}],
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "answer")
        self.assertEqual(result["usage"], {"prompt_tokens": 4, "completion_tokens": 6})
        self.assertEqual(result["provenance"], {"execution_job_ids": ["job-1"], "execution_node_ids": ["node-a", "node-b"]})
        self.assertEqual(backend.calls[0]["model_id"], "demo-model")
        self.assertEqual(backend.calls[0]["max_tokens"], 32)
        self.assertEqual(len(backend.calls[0]["tools"]), 1)

    def test_legacy_backend_receives_only_its_declared_contract(self):
        backend = _LegacyBackend()
        caller = make_backend_model_caller(backend, model_id="legacy-model", max_tokens=32)
        result = caller([{"role": "user", "content": "hello"}], [{"name": "ignored"}])
        self.assertEqual(result["choices"][0]["message"]["content"], "legacy")
        self.assertEqual(backend.calls[0][0], "legacy-model")

    def test_invalid_backend_result_fails_closed(self):
        caller = BackendModelCaller(_InvalidBackend(), "demo-model")
        with self.assertRaises(ModelCallerError):
            caller([], [])

    def test_backend_carries_provider_resource_usage(self):
        result = BackendModelCaller(_ResourceBackend(), "metered-model")([], [])
        self.assertEqual(result["usage"]["gpu_milliseconds"], 11)
        self.assertEqual(result["usage"]["external_cost_micros"], 19)

    def test_existing_synthetic_backend_uses_the_same_agent_shape(self):
        caller = make_backend_model_caller(
            SyntheticInferenceBackend(),
            model_id="demo-model",
            max_tokens=64,
        )
        result = caller([{"role": "user", "content": "hello"}], [])
        self.assertIn("ComputeMesh", result["choices"][0]["message"]["content"])
        self.assertGreaterEqual(result["usage"]["completion_tokens"], 0)

    def test_mesh_dispatch_caller_binds_turn_and_forwards_tool_schemas(self):
        dispatcher = _Dispatcher()
        caller = MeshDispatchModelCaller(
            dispatcher,
            session_id="sess-1",
            turn_id="turn-1",
            model_id="mesh-model",
        )
        result = caller(
            [{"role": "user", "content": "hello"}],
            [{"type": "function", "function": {"name": "read_status"}}],
        )
        self.assertEqual(result["choices"][0]["message"]["content"], "mesh answer")
        self.assertEqual(result["usage"], {"prompt_tokens": 7, "completion_tokens": 3})
        self.assertEqual(result["provenance"], {"execution_job_ids": ["mesh-job-1"], "execution_node_ids": ["node-mesh"]})
        request = dispatcher.calls[0]
        self.assertEqual(request["session_id"], "sess-1")
        self.assertEqual(request["turn_id"], "turn-1")
        self.assertEqual(request["model_id"], "mesh-model")
        self.assertEqual(request["payload"]["tools"][0]["function"]["name"], "read_status")
        self.assertTrue(request["idempotency_key"].endswith(":1"))

    def test_mesh_dispatch_caller_sends_private_settlement_evidence_to_observer(self):
        observed = []
        caller = MeshDispatchModelCaller(
            _Dispatcher(),
            session_id="sess-1",
            turn_id="turn-billing",
            model_id="mesh-model",
            result_observer=observed.append,
        )
        caller([{"role": "user", "content": "hello"}], [])
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].prompt_tokens, 7)
        self.assertEqual(observed[0].completion_tokens, 3)
        self.assertEqual(observed[0].provider_shares, (("node-mesh", 1.0),))
        self.assertTrue(observed[0].execution_job_id.startswith("mesh-agent-"))

    def test_mesh_dispatch_caller_preserves_native_tool_calls(self):
        caller = MeshDispatchModelCaller(
            _ToolDispatcher(),
            session_id="sess-1",
            turn_id="turn-1",
            model_id="mesh-model",
        )
        result = caller([{"role": "user", "content": "status"}], [{"type": "function"}])
        self.assertEqual(result["choices"][0]["message"]["content"], "")
        self.assertEqual(result["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "read_status")

    def test_mesh_dispatch_caller_preserves_tool_call_history_on_wire(self):
        dispatcher = _Dispatcher()
        caller = MeshDispatchModelCaller(
            dispatcher,
            session_id="sess-1",
            turn_id="turn-1",
            model_id="mesh-model",
        )
        caller([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_status", "arguments": "{}"},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "read_status", "content": "ok"},
        ], [])
        messages = dispatcher.calls[0]["payload"]["messages"]
        self.assertEqual(messages[0]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(messages[1]["tool_call_id"], "call_1")


if __name__ == "__main__":
    unittest.main()
