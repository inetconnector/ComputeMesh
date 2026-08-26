from __future__ import annotations

from pathlib import Path
import threading
import time
import unittest

from services.gateway.inference_backend import InferenceBackendError
from services.orchestrator.live_shared_backend import LiveSharedInferenceBackend


class LiveRequestCancelRegistryTests(unittest.TestCase):
    def _backend(self):
        return LiveSharedInferenceBackend(
            registry=object(),
            store=object(),
            resolver=object(),
            llama_server=Path("llama-server"),
            work_root=Path("work"),
            allow_experimental=True,
            max_attempts=1,
        )

    def test_owner_request_id_can_signal_active_cancel_event(self):
        backend = self._backend()
        entered = threading.Event()
        observed = threading.Event()
        errors: list[Exception] = []

        def fake_complete(*, request_id, model_id, messages, cancel_event):
            entered.set()
            if not cancel_event.wait(2):
                raise AssertionError("cancel event was not signalled")
            observed.set()
            raise InferenceBackendError("shared request was cancelled")

        backend._complete = fake_complete  # type: ignore[method-assign]

        def run():
            try:
                backend.complete_for_request(
                    request_id="client-request-1",
                    model_id="model",
                    messages=[{"role": "user", "content": "x"}],
                )
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(entered.wait(1))
        self.assertTrue(backend.cancel("client-request-1"))
        thread.join(timeout=3)
        self.assertTrue(observed.is_set())
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        self.assertFalse(backend.cancel("client-request-1"))

    def test_unknown_request_cannot_be_cancelled(self):
        backend = self._backend()
        self.assertFalse(backend.cancel("not-active"))


if __name__ == "__main__":
    unittest.main()
