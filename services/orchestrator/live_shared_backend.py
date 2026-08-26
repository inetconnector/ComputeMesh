"""Gateway backend that resolves fresh live placement for every shared request."""
from __future__ import annotations

from pathlib import Path
import secrets
from typing import Any

from runtime.llama.shared_request_live import run_live_shared_request
from services.gateway.inference_backend import BackendResult, InferenceBackendError
from services.gateway.execution_attestation import VerificationKeyResolver
from services.orchestrator.authenticated_attestation_transport import SessionAuthenticatedAttestationTransport
from services.orchestrator.live_shared_runtime import LiveExecutionPlan, LiveSharedRuntimeRegistry, LiveSharedRuntimeError
from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.shared_request_backend import SharedRequestOrchestratedBackend


class LiveSharedInferenceBackend:
    """Resolve current nodes/benchmarks/placement, execute, and safely re-place once.

    Each attempt is a separate durable orchestrator job. A retry is permitted only
    before any BackendResult has been returned and only when a fresh scheduler pass
    chooses a different provider set. The failed attempt remains FAILED in durable
    state and its reservations are released by SharedRequestOrchestratedBackend.
    """

    def __init__(
        self,
        *,
        registry: LiveSharedRuntimeRegistry,
        store: SQLiteStateStore,
        resolver: VerificationKeyResolver,
        llama_server: Path,
        work_root: Path,
        allow_experimental: bool,
        lease_seconds: int = 600,
        max_attempts: int = 2,
        startup_timeout: float = 300.0,
        request_timeout: float = 300.0,
    ) -> None:
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be 1..3")
        if startup_timeout <= 0 or startup_timeout > 900:
            raise ValueError("startup_timeout must be within (0,900]")
        if request_timeout <= 0 or request_timeout > 900:
            raise ValueError("request_timeout must be within (0,900]")
        self.registry = registry
        self.store = store
        self.resolver = resolver
        self.llama_server = Path(llama_server)
        self.work_root = Path(work_root)
        self.allow_experimental = allow_experimental
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout

    def _plan(self, model_id: str) -> LiveExecutionPlan:
        try:
            return self.registry.build_execution_plan(
                model_id,
                allow_experimental=self.allow_experimental,
            )
        except LiveSharedRuntimeError as exc:
            raise InferenceBackendError("live shared runtime is not dispatchable") from exc

    def _backend_for_attempt(
        self,
        *,
        live: LiveExecutionPlan,
        attempt_job_id: str,
    ) -> SharedRequestOrchestratedBackend:
        try:
            transport = SessionAuthenticatedAttestationTransport(
                sessions=self.registry,
                client=self.registry.control_client,
            )
        except LiveSharedRuntimeError as exc:
            raise InferenceBackendError("live shared control plane is not dispatchable") from exc

        def runner(**kwargs: Any):
            kwargs.pop("bundle_path", None)
            return run_live_shared_request(
                plan=live.trial_plan,
                startup_timeout=self.startup_timeout,
                request_timeout=self.request_timeout,
                **kwargs,
            )

        return SharedRequestOrchestratedBackend(
            store=self.store,
            placement=live.placement,
            bundle_path=Path("."),
            llama_server=self.llama_server,
            model_path=live.model_path,
            worker_rpc=live.worker_rpc,
            work_root=self.work_root,
            attestation_transport=transport,
            attestation_resolver=self.resolver,
            lease_seconds=self.lease_seconds,
            id_factory=lambda: attempt_job_id,
            runner=runner,
        )

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        recovery_id = f"live-{secrets.token_hex(10)}"
        previous_provider_sets: set[frozenset[str]] = set()
        last_error: InferenceBackendError | None = None

        for attempt in range(1, self.max_attempts + 1):
            live = self._plan(model_id)
            provider_set = frozenset(live.placement.provider_node_ids)
            if provider_set in previous_provider_sets:
                if last_error is not None:
                    raise InferenceBackendError(
                        "live shared retry refused because scheduler selected the failed provider set again"
                    ) from last_error
                raise InferenceBackendError("live shared placement repeated within one recovery group")
            previous_provider_sets.add(provider_set)
            attempt_job_id = f"{recovery_id}-a{attempt}"
            backend = self._backend_for_attempt(live=live, attempt_job_id=attempt_job_id)
            try:
                return backend.complete(model_id=model_id, messages=messages)
            except InferenceBackendError as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise
                # No BackendResult was returned, so no response or provider settlement
                # escaped this attempt. A retry must obtain a fresh placement above.
                continue

        assert last_error is not None
        raise last_error
