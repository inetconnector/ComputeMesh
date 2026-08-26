"""Gateway backend that resolves fresh live placement for every shared request."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.llama.shared_request_live import run_live_shared_request
from services.gateway.inference_backend import BackendResult, InferenceBackendError
from services.gateway.execution_attestation import VerificationKeyResolver
from services.orchestrator.authenticated_attestation_transport import SessionAuthenticatedAttestationTransport
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry, LiveSharedRuntimeError
from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.shared_request_backend import SharedRequestOrchestratedBackend


class LiveSharedInferenceBackend:
    """Resolve current nodes/benchmarks/placement, then execute one signed request."""

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
    ) -> None:
        self.registry = registry
        self.store = store
        self.resolver = resolver
        self.llama_server = Path(llama_server)
        self.work_root = Path(work_root)
        self.allow_experimental = allow_experimental
        self.lease_seconds = lease_seconds

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        try:
            live = self.registry.build_execution_plan(
                model_id,
                allow_experimental=self.allow_experimental,
            )
            transport = SessionAuthenticatedAttestationTransport(
                sessions=self.registry,
                client=self.registry.control_client,
            )
        except LiveSharedRuntimeError as exc:
            raise InferenceBackendError("live shared runtime is not dispatchable") from exc

        def runner(**kwargs: Any):
            kwargs.pop("bundle_path", None)
            return run_live_shared_request(
                plan=live.trial_plan,
                **kwargs,
            )

        backend = SharedRequestOrchestratedBackend(
            store=self.store,
            placement=live.placement,
            bundle_path=Path("."),  # ignored by the live runner; retained for legacy constructor compatibility
            llama_server=self.llama_server,
            model_path=live.model_path,
            worker_rpc=live.worker_rpc,
            work_root=self.work_root,
            attestation_transport=transport,
            attestation_resolver=self.resolver,
            lease_seconds=self.lease_seconds,
            runner=runner,
        )
        return backend.complete(model_id=model_id, messages=messages)
