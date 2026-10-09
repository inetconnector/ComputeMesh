from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.gateway.live_server import _start_optional_agent_worker


class _Runtime:
    def __init__(self) -> None:
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def close(self):
        self.closed = True
        return True


class LiveServerAgentWorkerTests(unittest.TestCase):
    def test_worker_is_not_started_without_explicit_switch(self):
        handler = SimpleNamespace()
        control_plane = SimpleNamespace(control_client=object())
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COMPUTEMESH_AGENTS_WORKER_ENABLED", None)
            with patch("services.gateway.agent_worker_runtime.build_gateway_agent_worker_runtime") as build:
                self.assertIsNone(
                    _start_optional_agent_worker(
                        handler_cls=handler,
                        control_plane=control_plane,
                    )
                )
                build.assert_not_called()

    def test_live_worker_receives_integrated_control_client_and_starts(self):
        runtime = _Runtime()
        backend = object()
        tool_registry = object()
        ledger = object()
        session_store = object()
        handler = SimpleNamespace(
            inference_engine=SimpleNamespace(backend=backend, tool_registry=tool_registry),
            ledger=ledger,
            _get_agent_session_store=lambda: session_store,
        )
        control_client = object()
        policy_resolver = object()
        control_plane = SimpleNamespace(control_client=control_client)
        with patch.dict(os.environ, {"COMPUTEMESH_AGENTS_WORKER_ENABLED": "1"}, clear=False), patch(
            "services.gateway.agent_worker_runtime.build_gateway_agent_worker_runtime",
            return_value=runtime,
        ) as build:
            result = _start_optional_agent_worker(
                handler_cls=handler,
                control_plane=control_plane,
                runtime_policy_resolver=policy_resolver,
            )
        self.assertIs(result, runtime)
        self.assertTrue(runtime.started)
        self.assertEqual(build.call_args.kwargs["backend"], backend)
        self.assertEqual(build.call_args.kwargs["session_store"], session_store)
        self.assertEqual(build.call_args.kwargs["tool_registry"], tool_registry)
        self.assertEqual(build.call_args.kwargs["ledger"], ledger)
        self.assertEqual(build.call_args.kwargs["control_client"], control_client)
        self.assertEqual(build.call_args.kwargs["runtime_policy_resolver"], policy_resolver)

    def test_partial_runtime_is_closed_when_startup_fails(self):
        runtime = _Runtime()
        handler = SimpleNamespace(
            inference_engine=SimpleNamespace(backend=object(), tool_registry=None),
            ledger=None,
            _get_agent_session_store=lambda: object(),
        )
        with patch.dict(os.environ, {"COMPUTEMESH_AGENTS_WORKER_ENABLED": "1"}, clear=False), patch(
            "services.gateway.agent_worker_runtime.build_gateway_agent_worker_runtime",
            return_value=runtime,
        ) as build:
            runtime.start = lambda: (_ for _ in ()).throw(RuntimeError("worker start failed"))
            with self.assertRaises(RuntimeError):
                _start_optional_agent_worker(
                    handler_cls=handler,
                    control_plane=SimpleNamespace(control_client=object()),
                )
        self.assertTrue(runtime.closed)
        self.assertEqual(build.call_count, 1)


if __name__ == "__main__":
    unittest.main()
