"""Request-context wrapper that makes live backend cancellation owner-addressable."""
from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator

from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import BackendResult, InferenceBackend
from services.orchestrator.settlement_recovery import acknowledge_job_settlement


class RequestContextBackend:
    """Dispatch to complete_for_request when a request id is bound to this thread."""

    def __init__(self, delegate: InferenceBackend, local: threading.local):
        self.delegate = delegate
        self.local = local

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        request_id = getattr(self.local, "request_id", None)
        complete_for_request = getattr(self.delegate, "complete_for_request", None)
        if request_id and callable(complete_for_request):
            result = complete_for_request(
                request_id=request_id,
                model_id=model_id,
                messages=messages,
            )
        else:
            result = self.delegate.complete(model_id=model_id, messages=messages)
        self.local.execution_job_id = result.execution_job_id
        return result


class CancellableInferenceEngine(InferenceEngine):
    """Track active request ownership and acknowledge live settlement after billing."""

    def __init__(self, *, ledger, metrics, teaser_manager, backend: InferenceBackend):
        self._request_local = threading.local()
        self._active_lock = threading.RLock()
        self._active_owners: dict[str, str] = {}
        self._delegate_backend = backend
        super().__init__(
            ledger=ledger,
            metrics=metrics,
            teaser_manager=teaser_manager,
            backend=RequestContextBackend(backend, self._request_local),
        )

    @staticmethod
    def validate_request_id(request_id: str) -> str:
        value = request_id.strip()
        if not (1 <= len(value) <= 128):
            raise ValueError("X-ComputeMesh-Request-ID must be 1..128 characters")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")
        if any(ch not in allowed for ch in value):
            raise ValueError("X-ComputeMesh-Request-ID contains invalid characters")
        return value

    @contextmanager
    def request_scope(self, request_id: str | None) -> Iterator[None]:
        previous = getattr(self._request_local, "request_id", None)
        if request_id:
            self._request_local.request_id = self.validate_request_id(request_id)
        else:
            self._request_local.request_id = None
        try:
            yield
        finally:
            self._request_local.request_id = previous

    def create_metered_completion(self, **kwargs: Any):
        request_id = getattr(self._request_local, "request_id", None)
        account_id = str(kwargs.get("account_id", ""))
        self._request_local.execution_job_id = None
        if request_id:
            with self._active_lock:
                existing = self._active_owners.get(request_id)
                if existing is not None:
                    raise ValueError("ComputeMesh request id is already active")
                self._active_owners[request_id] = account_id
        try:
            result = super().create_metered_completion(**kwargs)
            execution_job_id = getattr(self._request_local, "execution_job_id", None)
            store = getattr(self._delegate_backend, "store", None)
            if execution_job_id and store is not None:
                try:
                    acknowledge_job_settlement(store, execution_job_id)
                except Exception:
                    # Billing has already committed. Returning an error here would invite
                    # a client retry and possible duplicate billing semantics. Startup
                    # settlement reconciliation repairs this narrow acknowledgement gap.
                    pass
            return result
        finally:
            self._request_local.execution_job_id = None
            if request_id:
                with self._active_lock:
                    self._active_owners.pop(request_id, None)

    def cancel_request(self, *, account_id: str, request_id: str) -> bool:
        request_id = self.validate_request_id(request_id)
        with self._active_lock:
            owner = self._active_owners.get(request_id)
        if owner is None or owner != account_id:
            return False
        cancel = getattr(self._delegate_backend, "cancel", None)
        if not callable(cancel):
            return False
        return bool(cancel(request_id))
