from __future__ import annotations

import unittest

from services.gateway.cancellable_inference import CancellableInferenceEngine, RequestContextBackend
from services.gateway.inference_backend import BackendResult


class _Delegate:
    def __init__(self):
        self.request_ids = []
        self.cancelled = []

    def complete(self, *, model_id, messages):
        return BackendResult("plain", 1, 1)

    def complete_for_request(self, *, request_id, model_id, messages):
        self.request_ids.append(request_id)
        return BackendResult("scoped", 1, 1)

    def cancel(self, request_id):
        self.cancelled.append(request_id)
        return True


class CancellableInferenceTests(unittest.TestCase):
    def _engine(self):
        delegate = _Delegate()
        engine = CancellableInferenceEngine(
            ledger=object(),
            metrics=object(),
            teaser_manager=object(),
            backend=delegate,
        )
        return engine, delegate

    def test_request_scope_routes_to_job_aware_backend(self):
        engine, delegate = self._engine()
        with engine.request_scope("req-123"):
            result = engine.backend.complete(model_id="model", messages=[])
        self.assertEqual(result.text, "scoped")
        self.assertEqual(delegate.request_ids, ["req-123"])

    def test_cancel_requires_matching_active_owner(self):
        engine, delegate = self._engine()
        with engine._active_lock:
            engine._active_owners["req-123"] = "acct-a"
        self.assertFalse(engine.cancel_request(account_id="acct-b", request_id="req-123"))
        self.assertTrue(engine.cancel_request(account_id="acct-a", request_id="req-123"))
        self.assertEqual(delegate.cancelled, ["req-123"])

    def test_invalid_request_id_is_rejected(self):
        engine, _ = self._engine()
        with self.assertRaises(ValueError):
            engine.validate_request_id("bad request id")


if __name__ == "__main__":
    unittest.main()
