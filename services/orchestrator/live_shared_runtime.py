"""Live execution inputs for public ComputeMesh shared inference.

Production selection is global and private: the public registry supplies a bounded
snapshot of currently usable nodes and measured network edges, verifies the signed
result, then executes it. The disclosed reference planner remains research-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import threading
from typing import Any

from protocol.node_session import NodeSessionState, SessionSnapshot
from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.shared_trial import TrialPlan
from services.gateway.placement_selection import PlacementSelection
from services.orchestrator.authenticated_attestation_transport import ATTESTATION_CAPABILITY, NodeControlClient
from services.orchestrator.placement_provider import (
    PlacementPlan,
    PlacementProvider,
    PlacementProviderError,
    ReferencePlacementProvider,
)


class LiveSharedRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveNodeState:
    session: SessionSnapshot
    profile: dict[str, Any]
    prefill: dict[str, Any]
    decode: dict[str, Any]
    rpc_endpoint: RpcEndpoint
    llama_build_number: int
    llama_build_commit: str


@dataclass(frozen=True)
class LiveModelState:
    model_id: str
    manifest: dict[str, Any]
    model_path: Path


@dataclass(frozen=True)
class LiveExecutionPlan:
    placement: PlacementSelection
    trial_plan: TrialPlan
    model_path: Path
    worker_rpc: RpcEndpoint


def _selection_from_plan(plan: PlacementPlan) -> PlacementSelection:
    return PlacementSelection(
        decision_id=plan.decision_id,
        model_id=plan.model_id,
        artifact_digest=plan.artifact_digest,
        provider_node_ids=tuple(item[0] for item in plan.layer_ranges),
        layer_ranges=plan.layer_ranges,
    )


class LiveSharedRuntimeRegistry:
    def __init__(self, *, placement_provider: PlacementProvider | None = None) -> None:
        self._lock = threading.RLock()
        self._nodes: dict[str, LiveNodeState] = {}
        self._models: dict[str, LiveModelState] = {}
        self._network: dict[tuple[str, str], dict[str, Any]] = {}
        self._control_client: NodeControlClient | None = None
        self._placement_provider: PlacementProvider = placement_provider or ReferencePlacementProvider()

    def set_placement_provider(self, provider: PlacementProvider) -> None:
        with self._lock:
            self._placement_provider = provider

    def register_node(self, state: LiveNodeState) -> None:
        node_id = state.session.node_id
        if not node_id or state.profile.get("node_id") != node_id:
            raise LiveSharedRuntimeError("live node profile/session identity mismatch")
        if state.llama_build_number < 1 or not state.llama_build_commit:
            raise LiveSharedRuntimeError("live node lacks concrete llama.cpp build identity")
        with self._lock:
            self._nodes[node_id] = state

    def register_model(self, state: LiveModelState) -> None:
        if not state.model_id or not isinstance(state.manifest, dict):
            raise LiveSharedRuntimeError("invalid live model state")
        with self._lock:
            self._models[state.model_id] = state

    def register_network_result(self, coordinator_node_id: str, worker_node_id: str, result: dict[str, Any]) -> None:
        if coordinator_node_id == worker_node_id:
            raise LiveSharedRuntimeError("network path requires distinct nodes")
        with self._lock:
            self._network[(coordinator_node_id, worker_node_id)] = dict(result)

    def set_control_client(self, client: NodeControlClient) -> None:
        with self._lock:
            self._control_client = client

    @property
    def control_client(self) -> NodeControlClient:
        with self._lock:
            if self._control_client is None:
                raise LiveSharedRuntimeError("live node control client is not registered")
            return self._control_client

    def get_session(self, node_id: str) -> SessionSnapshot:
        with self._lock:
            try:
                return self._nodes[node_id].session
            except KeyError as exc:
                raise KeyError(node_id) from exc

    @staticmethod
    def _session_ready(session: SessionSnapshot, *, now: datetime | None = None) -> bool:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return (
            session.state in {NodeSessionState.CAPABILITIES_NEGOTIATED, NodeSessionState.PROFILE_SYNCED, NodeSessionState.READY}
            and session.credential_expires_at is not None
            and session.credential_expires_at.astimezone(UTC) > current
            and ATTESTATION_CAPABILITY in session.negotiated_capabilities
        )

    def is_node_control_healthy(self, node_id: str) -> bool:
        with self._lock:
            state = self._nodes.get(node_id)
            client = self._control_client
        if state is None or not self._session_ready(state.session) or client is None:
            return False
        probe = getattr(client, "is_connected", None)
        if not callable(probe):
            return False
        try:
            return bool(probe(node_id))
        except Exception:
            return False

    @staticmethod
    def _trial_from_plan(plan: PlacementPlan, model: LiveModelState, coordinator: LiveNodeState) -> TrialPlan:
        ranges = tuple(
            {"node_id": node, "start_layer": start, "end_layer_exclusive": end}
            for node, start, end in plan.layer_ranges
        )
        return TrialPlan(
            bundle_id="live:" + plan.decision_id,
            placement_decision_id=plan.decision_id,
            coordinator_node_id=plan.coordinator_node_id,
            worker_node_id=plan.worker_node_id,
            coordinator_kind=plan.coordinator_kind,
            coordinator_name=plan.coordinator_name,
            llama_build_commit=coordinator.llama_build_commit,
            llama_build_number=coordinator.llama_build_number,
            model_basename=model.model_path.name,
            model_size_bytes=plan.artifact_size_bytes,
            model_sha256=plan.artifact_digest.removeprefix("sha256:"),
            tensor_split=plan.tensor_split,
            layer_ranges=(ranges[0], ranges[1]),
        )

    def _reference_plan(self, model: LiveModelState, nodes: list[LiveNodeState], networks: dict[tuple[str, str], dict[str, Any]], provider: PlacementProvider) -> PlacementPlan:
        failures: list[str] = []
        for coordinator in nodes:
            for worker in nodes:
                if coordinator is worker:
                    continue
                coord_id, worker_id = str(coordinator.session.node_id), str(worker.session.node_id)
                network = networks.get((coord_id, worker_id))
                if network is None:
                    continue
                if coordinator.llama_build_number != worker.llama_build_number or coordinator.llama_build_commit.lower() != worker.llama_build_commit.lower():
                    continue
                try:
                    return provider.decide(
                        coordinator_profile=coordinator.profile,
                        worker_profile=worker.profile,
                        model_manifest=model.manifest,
                        coordinator_prefill=coordinator.prefill,
                        coordinator_decode=coordinator.decode,
                        worker_prefill=worker.prefill,
                        worker_decode=worker.decode,
                        network_result=network,
                    )
                except (PlacementProviderError, ValueError, KeyError) as exc:
                    failures.append(f"{coord_id}->{worker_id}: {exc}")
        detail = "; ".join(failures[:4])
        raise LiveSharedRuntimeError("no reference two-node placement is feasible" + (f": {detail}" if detail else ""))

    def build_execution_plan(self, model_id: str, *, allow_experimental: bool) -> LiveExecutionPlan:
        with self._lock:
            model = self._models.get(model_id)
            if model is None:
                raise LiveSharedRuntimeError(f"model {model_id!r} is not registered in live runtime")
            states = list(self._nodes.values())
            networks = dict(self._network)
            provider = self._placement_provider

        nodes = [state for state in states if state.session.node_id and self.is_node_control_healthy(str(state.session.node_id))]
        nodes.sort(key=lambda item: str(item.session.node_id))
        if len(nodes) < 2:
            raise LiveSharedRuntimeError("fewer than two authenticated connected attestation-capable nodes are live")

        if isinstance(provider, ReferencePlacementProvider):
            if not allow_experimental:
                raise LiveSharedRuntimeError("reference M1 placement requires explicit experimental opt-in")
            plan = self._reference_plan(model, nodes, networks, provider)
        else:
            candidates = [
                {
                    "node_id": str(state.session.node_id),
                    "profile": state.profile,
                    "prefill": state.prefill,
                    "decode": state.decode,
                    "runtime": {
                        "llama_build_number": state.llama_build_number,
                        "llama_build_commit": state.llama_build_commit,
                    },
                    "capacity": {"control_healthy": True},
                }
                for state in nodes
            ]
            network_edges = [
                {"source_node_id": source, "target_node_id": target, "result": result}
                for (source, target), result in sorted(networks.items())
                if source in {item["node_id"] for item in candidates} and target in {item["node_id"] for item in candidates}
            ]
            try:
                plan = provider.decide(
                    model_manifest=model.manifest,
                    candidates=candidates,
                    network_edges=network_edges,
                    constraints={"topology": "shared_contiguous_layers", "executor_max_stages": 2},
                )
            except (PlacementProviderError, ValueError, KeyError) as exc:
                raise LiveSharedRuntimeError(f"private global placement failed: {exc}") from exc

        by_id = {str(state.session.node_id): state for state in nodes}
        coordinator = by_id.get(plan.coordinator_node_id)
        worker = by_id.get(plan.worker_node_id)
        if coordinator is None or worker is None:
            raise LiveSharedRuntimeError("signed placement selected a node outside the submitted live snapshot")
        if (plan.coordinator_node_id, plan.worker_node_id) not in networks:
            raise LiveSharedRuntimeError("signed placement selected an unmeasured network path")
        if coordinator.llama_build_number != worker.llama_build_number or coordinator.llama_build_commit.lower() != worker.llama_build_commit.lower():
            raise LiveSharedRuntimeError("signed placement selected runtime-incompatible nodes")
        if plan.model_id != model_id:
            raise LiveSharedRuntimeError("signed placement model mismatch")

        return LiveExecutionPlan(
            placement=_selection_from_plan(plan),
            trial_plan=self._trial_from_plan(plan, model, coordinator),
            model_path=model.model_path,
            worker_rpc=worker.rpc_endpoint,
        )


LIVE_SHARED_RUNTIME = LiveSharedRuntimeRegistry()
