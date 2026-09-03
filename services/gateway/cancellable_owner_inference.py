"""Cancellation/request-id support without regressing unified-owner economics."""
from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator

from services.gateway.inference_backend import BackendResult, InferenceBackend
from services.gateway.owner_inference import UnifiedOwnerInferenceEngine
from services.orchestrator.settlement_recovery import acknowledge_job_settlement


class _OwnerRequestContextBackend:
    """Route a live request id to the backend while preserving BackendResult intact."""

    def __init__(self, delegate: InferenceBackend, local: threading.local) -> None:
        self.delegate = delegate
        self.local = local

    def complete(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> BackendResult:
        request_id = getattr(self.local, "request_id", None)
        complete_for_request = getattr(self.delegate, "complete_for_request", None)
        if request_id and callable(complete_for_request):
            try:
                result = complete_for_request(
                    request_id=request_id,
                    model_id=model_id,
                    messages=messages,
                    max_tokens=max_tokens,
                )
            except TypeError:
                result = complete_for_request(
                    request_id=request_id,
                    model_id=model_id,
                    messages=messages,
                )
        else:
            try:
                result = self.delegate.complete(
                    model_id=model_id,
                    messages=messages,
                    max_tokens=max_tokens,
                )
            except TypeError:
                result = self.delegate.complete(model_id=model_id, messages=messages)
        self.local.execution_job_id = result.execution_job_id
        return result


class CancellableUnifiedOwnerInferenceEngine(UnifiedOwnerInferenceEngine):
    """Unified owner billing plus owner-addressable cancellation for live serving."""

    def __init__(self, *, backend: InferenceBackend, **kwargs: Any) -> None:
        self._request_local = threading.local()
        self._active_lock = threading.RLock()
        self._active_owners: dict[str, str] = {}
        self._delegate_backend = backend
        super().__init__(
            backend=_OwnerRequestContextBackend(backend, self._request_local),
            **kwargs,
        )

    @staticmethod
    def validate_request_id(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("ComputeMesh request id must be a string")
        request_id = value.strip()
        if not request_id or len(request_id) > 128:
            raise ValueError("ComputeMesh request id must be between 1 and 128 characters")
        if not all(char.isalnum() or char in "-_.:" for char in request_id):
            raise ValueError("ComputeMesh request id contains invalid characters")
        return request_id

    @contextmanager
    def request_scope(self, request_id: str | None) -> Iterator[None]:
        previous = getattr(self._request_local, "request_id", None)
        self._request_local.request_id = (
            self.validate_request_id(request_id) if request_id else None
        )
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
                    # Owner settlement is already durable; backend acknowledgement is
                    # recoverable and must not turn a paid completion into an error.
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
