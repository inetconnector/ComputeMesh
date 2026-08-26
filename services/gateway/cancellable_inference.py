"""Request-context wrapper that makes live backend cancellation owner-addressable."""
from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator

from services.billing.ledger import DEFAULT_NETWORK_FEE_BPS, DEFAULT_PRICE_TIERS
from services.gateway.catalog import resolve_model_id
from services.gateway.inference import InferenceEngine
from services.gateway.inference_backend import BackendResult, InferenceBackend
from services.orchestrator.billing_intent import BillingIntentStore
from services.orchestrator.settlement_recovery import acknowledge_job_settlement


class RequestContextBackend:
    """Dispatch to complete_for_request and durably snapshot billing before return."""

    def __init__(
        self,
        delegate: InferenceBackend,
        local: threading.local,
        billing_intents: BillingIntentStore | None,
    ):
        self.delegate = delegate
        self.local = local
        self.billing_intents = billing_intents

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
        context = getattr(self.local, "billing_context", None)
        if (
            self.billing_intents is not None
            and result.execution_job_id
            and result.provider_shares is not None
            and isinstance(context, dict)
        ):
            self.billing_intents.put_pending(
                job_id=result.execution_job_id,
                account_id=context["account_id"],
                model_id=context["model_id"],
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                provider_shares=result.provider_shares,
                network_fee_bps=context["network_fee_bps"],
                prompt_micro_per_token=context["prompt_micro_per_token"],
                completion_micro_per_token=context["completion_micro_per_token"],
            )
        return result


class CancellableInferenceEngine(InferenceEngine):
    """Track ownership and durably bridge verified execution to billing."""

    def __init__(self, *, ledger, metrics, teaser_manager, backend: InferenceBackend):
        self._request_local = threading.local()
        self._active_lock = threading.RLock()
        self._active_owners: dict[str, str] = {}
        self._delegate_backend = backend
        store = getattr(backend, "store", None)
        self.billing_intents = BillingIntentStore(store) if store is not None else None
        super().__init__(
            ledger=ledger,
            metrics=metrics,
            teaser_manager=teaser_manager,
            backend=RequestContextBackend(backend, self._request_local, self.billing_intents),
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
        canonical_model = resolve_model_id(str(kwargs.get("model_id", "")))
        tier = DEFAULT_PRICE_TIERS.get(
            canonical_model,
            DEFAULT_PRICE_TIERS["qwen/qwen2.5-7b-instruct"],
        )
        is_self_compute = bool(kwargs.get("is_provider_self_compute", False))
        configured_fee = getattr(self.ledger, "network_fee_bps", DEFAULT_NETWORK_FEE_BPS)
        fee_bps = 0 if is_self_compute else int(configured_fee)

        self._request_local.execution_job_id = None
        self._request_local.billing_context = {
            "account_id": account_id,
            "model_id": canonical_model,
            "network_fee_bps": fee_bps,
            "prompt_micro_per_token": tier.prompt_micro_per_token,
            "completion_micro_per_token": tier.completion_micro_per_token,
        }
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
            if execution_job_id and self.billing_intents is not None:
                try:
                    self.billing_intents.mark_recorded(execution_job_id)
                except Exception:
                    pass
            if execution_job_id and store is not None:
                try:
                    acknowledge_job_settlement(store, execution_job_id)
                except Exception:
                    pass
            return result
        finally:
            self._request_local.execution_job_id = None
            self._request_local.billing_context = None
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
