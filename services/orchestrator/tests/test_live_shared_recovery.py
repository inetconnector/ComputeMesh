from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from services.gateway.inference_backend import BackendResult, InferenceBackendError
from services.orchestrator.live_shared_backend import LiveSharedInferenceBackend
from services.orchestrator.persistence import SQLiteStateStore


class _Registry:
    def __init__(self, plans, *, healthy=None):
        self.plans = list(plans)
        self.calls = 0
        self.control_client = object()
        self.healthy = set(healthy or {"node-a", "node-b", "node-c", "node-d"})

    def build_execution_plan(self, model_id: str, *, allow_experimental: bool):
        self.calls += 1
        if not self.plans:
            raise AssertionError("unexpected plan request")
        return self.plans.pop(0)

    def is_node_control_healthy(self, node_id: str) -> bool:
        return node_id in self.healthy


def _plan(*nodes: str):
    return SimpleNamespace(
        placement=SimpleNamespace(
            provider_node_ids=tuple(nodes),
            model_id="model",
            decision_id="decision-" + "-".join(nodes),
        ),
        trial_plan=SimpleNamespace(),
        model_path=Path("model.gguf"),
        worker_rpc=SimpleNamespace(),
    )


class _FakeAttemptBackend:
    outcomes = []
    jobs = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.jobs.append(kwargs["id_factory"]())

    def complete(self, *, model_id, messages):
        outcome = self.__class__.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class LiveSharedRecoveryTests(unittest.TestCase):
    def setUp(self):
        _FakeAttemptBackend.outcomes = []
        _FakeAttemptBackend.jobs = []

    def _backend(self, registry, *, max_attempts=2, store=None, health_poll_seconds=0.01):
        return LiveSharedInferenceBackend(
            registry=registry,
            store=store if store is not None else object(),
            resolver=object(),
            llama_server=Path("llama-server"),
            work_root=Path("work"),
            allow_experimental=True,
            max_attempts=max_attempts,
            startup_timeout=12.0,
            request_timeout=34.0,
            health_poll_seconds=health_poll_seconds,
        )

    @patch("services.orchestrator.live_shared_backend.SharedRequestOrchestratedBackend", _FakeAttemptBackend)
    def test_failed_attempt_can_replan_to_different_provider_set(self):
        registry = _Registry([_plan("node-a", "node-b"), _plan("node-c", "node-d")])
        expected = BackendResult("ok", 2, 3, execution_job_id="final")
        _FakeAttemptBackend.outcomes = [InferenceBackendError("first failed"), expected]
        result = self._backend(registry).complete(model_id="model", messages=[{"role": "user", "content": "x"}])
        self.assertIs(result, expected)
        self.assertEqual(registry.calls, 2)
        self.assertEqual(len(_FakeAttemptBackend.jobs), 2)
        prefix1, suffix1 = _FakeAttemptBackend.jobs[0].rsplit("-a", 1)
        prefix2, suffix2 = _FakeAttemptBackend.jobs[1].rsplit("-a", 1)
        self.assertEqual(prefix1, prefix2)
        self.assertEqual((suffix1, suffix2), ("1", "2"))

    @patch("services.orchestrator.live_shared_backend.SharedRequestOrchestratedBackend", _FakeAttemptBackend)
    def test_retry_refuses_same_failed_provider_set(self):
        registry = _Registry([_plan("node-a", "node-b"), _plan("node-b", "node-a")])
        _FakeAttemptBackend.outcomes = [InferenceBackendError("first failed")]
        with self.assertRaisesRegex(InferenceBackendError, "failed provider set again"):
            self._backend(registry).complete(model_id="model", messages=[{"role": "user", "content": "x"}])
        self.assertEqual(len(_FakeAttemptBackend.jobs), 1)

    @patch("services.orchestrator.live_shared_backend.SharedRequestOrchestratedBackend", _FakeAttemptBackend)
    def test_max_attempts_one_never_retries(self):
        registry = _Registry([_plan("node-a", "node-b"), _plan("node-c", "node-d")])
        _FakeAttemptBackend.outcomes = [InferenceBackendError("first failed")]
        with self.assertRaises(InferenceBackendError):
            self._backend(registry, max_attempts=1).complete(model_id="model", messages=[])
        self.assertEqual(registry.calls, 1)

    def test_health_watch_aborts_when_selected_provider_disconnects(self):
        registry = _Registry([], healthy={"node-a", "node-b"})
        backend = self._backend(registry)
        abort = threading.Event()
        stop = threading.Event()
        watcher = backend._start_health_watch(
            provider_node_ids=("node-a", "node-b"),
            abort_event=abort,
            stop_event=stop,
        )
        registry.healthy.remove("node-b")
        self.assertTrue(abort.wait(1.0))
        stop.set()
        watcher.join(timeout=1.0)
        self.assertFalse(watcher.is_alive())

    @patch("services.orchestrator.live_shared_backend.run_live_shared_request")
    def test_runtime_deadlines_are_forwarded(self, run):
        registry = _Registry([_plan("node-a", "node-b")])
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStateStore(Path(tmp) / "state.sqlite3")
            try:
                backend = self._backend(registry, store=store)
                live = registry.build_execution_plan("model", allow_experimental=True)
                attempt = backend._backend_for_attempt(live=live, attempt_job_id="job-a1")
                run.return_value = object()
                attempt.runner(job_id="job-a1", bundle_path=Path("ignored"), llama_server=Path("x"), model_path=Path("y"), worker_rpc=object(), output_dir=Path("z"), prompt="p")
                self.assertEqual(run.call_args.kwargs["startup_timeout"], 12.0)
                self.assertEqual(run.call_args.kwargs["request_timeout"], 34.0)
                self.assertIn("abort_event", run.call_args.kwargs)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
