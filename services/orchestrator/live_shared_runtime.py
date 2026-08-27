"""Live control-plane inputs for gateway shared inference.

The registry is intentionally in-memory: node sessions, profiles, benchmarks and
control-channel clients are runtime state, not pre-positioned settlement files.
A fresh placement is built for each request from the current registered state.
Production placement policy is accessed only through PlacementProvider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from protocol.node_session import NodeSessionState, SessionSnapshot
from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.shared_trial import TrialPlan
from services.gateway.placement_selection import PlacementSelection, PlacementSelectionError
from services.orchestrator.authenticated_attestation_transport import (
    ATTESTATION_CAPABILITY,
    NodeControlClient,
)
from services.orchestrator.placement_provider import (
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


def _selection_from_decision(decision: dict[str, Any], *, allow_experimental: bool) -> PlacementSelection:
    from pathlib import Path as _Path
    import json

    schema_path = _Path(__file__).resolve().parents[1] / "scheduler" / "placement_decision.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(decision),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "$"
        raise PlacementSelectionError(f"live placement invalid at {where}: {first.message}")
    recommendation = decision["recommendation"]
    if recommendation["production_scheduling"] is not False:
        raise PlacementSelectionError("unexpected production_scheduling contract")
    if not allow_experimental:
        raise PlacementSelectionError("live M1 shared placement requires explicit experimental opt-in")
    if recommendation["mode"] != "shared_experiment":
        raise PlacementSelectionError("scheduler did not recommend a shared experiment")
    if not all(bool(item["passed"]) for item in decision["hard_constraints"]):
        raise PlacementSelectionError("placement hard constraints are not all satisfied")
    matches = [c for c in decision["candidates"] if c["mode"] == "shared_contiguous_layers"]
    if len(matches) != 1 or not matches[0]["feasible"]:
        raise PlacementSelectionError("no unique feasible shared placement")
    ranges = matches[0]["layer_ranges"]
    if len(ranges) != 2:
        raise PlacementSelectionError("live serving currently requires exactly two layer ranges")
    layer_ranges = tuple(
        (str(item["node_id"]), int(item["start_layer"]), int(item["end_layer_exclusive"]))
        for item in ranges
    )
    ordered = tuple(sorted(layer_ranges, key=lambda item: item[1]))
    if ordered[0][1] != 0 or ordered[0][2] != ordered[1][1] or ordered[-1][2] != int(decision["model"]["layer_count"]):
        raise PlacementSelectionError("live placement layer ranges are not contiguous/full")
    nodes = tuple(item[0] for item in layer_ranges)
    expected = {
        str(decision["nodes"]["coordinator"]["node_id"]),
        str(decision["nodes"]["worker"]["node_id"]),
    }
    if set(nodes) != expected or len(set(nodes)) != 2:
        raise PlacementSelectionError("live placement nodes do not match scheduler decision")
    return PlacementSelection(
        decision_id=str(decision["decision_id"]),
        model_id=str(decision["model"]["model_id"]),
        artifact_digest=str(decision["model"]["artifact_digest"]),
        provider_node_ids=nodes,
        layer_ranges=layer_ranges,
    )


class LiveSharedRuntimeRegistry:
    """Thread-safe source of current scheduler and authenticated-session inputs."""

    def __init__(self, *, placement_provider: PlacementProvider | None = None) -> None:
        self._lock = threading.RLock()
        self._nodes: dict[str, LiveNodeState] = {}
        self._models: dict[str, LiveModelState] = {}
        self._network: dict[tuple[str, str], dict[str, Any]] = {}
        self._control_client: NodeControlClient | None = None
        # Reference planner preserves disclosed M1 behavior. Production startup must
        # explicitly inject RemotePlacementProvider; private policy never lives here.
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
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return (
            session.state in {NodeSessionState.CAPABILITIES_NEGOTIATED, NodeSessionState.PROFILE_SYNCED, NodeSessionState.READY}
            and session.credential_expires_at is not None
            and session.credential_expires_at.astimezone(timezone.utc) > current
            and ATTESTATION_CAPABILITY in session.negotiated_capabilities
        )

    def is_node_control_healthy(self, node_id: str) -> bool:
        with self._lock:
            state = self._nodes.get(node_id)
            client = self._control_client
        if state is None or not self._session_ready(state.session):
            return False
        if client is None:
            return False
        probe = getattr(client, "is_connected", None)
        if not callable(probe):
            return False
        try:
            return bool(probe(node_id))
        except Exception:
            return False

    def build_execution_plan(self, model_id: str, *, allow_experimental: bool) -> LiveExecutionPlan:
        with self._lock:
            model = self._models.get(model_id)
            if model is None:
                raise LiveSharedRuntimeError(f"model {model_id!r} is not registered in live runtime")
            states = list(self._nodes.values())
            networks = dict(self._network)
            placement_provider = self._placement_provider
        nodes = [state for state in states if state.session.node_id and self.is_node_control_healthy(str(state.session.node_id))]
        nodes.sort(key=lambda item: str(item.session.node_id))
        if len(nodes) < 2:
            raise LiveSharedRuntimeError("fewer than two authenticated connected attestation-capable nodes are live")

        failures: list[str] = []
        for coordinator in nodes:
            for worker in nodes:
                if coordinator is worker:
                    continue
                coord_id = str(coordinator.session.node_id)
                worker_id = str(worker.session.node_id)
                network = networks.get((coord_id, worker_id))
                if network is None:
                    continue
                if coordinator.llama_build_number != worker.llama_build_number or coordinator.llama_build_commit.lower() != worker.llama_build_commit.lower():
                    failures.append(f"{coord_id}->{worker_id}: runtime build mismatch")
                    continue
                try:
                    decision = placement_provider.decide(
                        coordinator_profile=coordinator.profile,
                        worker_profile=worker.profile,
                        model_manifest=model.manifest,
                        coordinator_prefill=coordinator.prefill,
                        coordinator_decode=coordinator.decode,
                        worker_prefill=worker.prefill,
                        worker_decode=worker.decode,
                        network_result=network,
                    )
                    placement = _selection_from_decision(decision, allow_experimental=allow_experimental)
                except (PlacementProviderError, PlacementSelectionError, ValueError, KeyError) as exc:
                    failures.append(f"{coord_id}->{worker_id}: {exc}")
                    continue

                shared = next(c for c in decision["candidates"] if c["mode"] == "shared_contiguous_layers")
                ranges = tuple(dict(item) for item in shared["layer_ranges"])
                artifact_digest = placement.artifact_digest.removeprefix("sha256:")
                model_record = decision["model"]
                coordinator_record = decision["nodes"]["coordinator"]
                trial = TrialPlan(
                    bundle_id="live:" + placement.decision_id,
                    placement_decision_id=placement.decision_id,
                    coordinator_node_id=coord_id,
                    worker_node_id=worker_id,
                    coordinator_kind=str(coordinator_record["kind"]),
                    coordinator_name=str(coordinator_record["name"]),
                    llama_build_commit=coordinator.llama_build_commit,
                    llama_build_number=coordinator.llama_build_number,
                    model_basename=model.model_path.name,
                    model_size_bytes=int(model_record["artifact_size_bytes"]),
                    model_sha256=artifact_digest,
                    tensor_split=(float(shared["tensor_split"][0]), float(shared["tensor_split"][1])),
                    layer_ranges=(ranges[0], ranges[1]),
                )
                return LiveExecutionPlan(placement=placement, trial_plan=trial, model_path=model.model_path, worker_rpc=worker.rpc_endpoint)
        detail = "; ".join(failures[:4])
        raise LiveSharedRuntimeError("no live two-node shared placement is currently feasible" + (f": {detail}" if detail else ""))


LIVE_SHARED_RUNTIME = LiveSharedRuntimeRegistry()
