from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from protocol.node_session import NodeSessionState, SessionSnapshot
from runtime.llama.rpc_spike import RpcEndpoint
from services.orchestrator.live_shared_runtime import (
    LiveModelState,
    LiveNodeState,
    LiveSharedRuntimeError,
    LiveSharedRuntimeRegistry,
)
from services.orchestrator.placement_provider import PlacementPlan
from services.scheduler.tests.test_placement import DIGEST, bench, manifest, profile


class _ControlClient:
    def __init__(self, connected=("node-a", "node-b")):
        self.connected = set(connected)

    def is_connected(self, node_id: str) -> bool:
        return node_id in self.connected

    def request(self, **kwargs):
        raise NotImplementedError


class _GlobalProvider:
    def __init__(self):
        self.calls = []

    def decide(self, **inputs):
        self.calls.append(inputs)
        ids = [item["node_id"] for item in inputs["candidates"]]
        assert ids == sorted(ids)
        assert len(ids) >= 3
        return PlacementPlan(
            decision_id="private-global-1",
            model_id="test-model",
            artifact_digest=DIGEST,
            artifact_size_bytes=8_000_000_000,
            layer_count=32,
            coordinator_node_id="node-b",
            coordinator_kind="gpu",
            coordinator_name="Test GPU",
            worker_node_id="node-c",
            layer_ranges=(("node-b", 0, 18), ("node-c", 18, 32)),
            tensor_split=(18.0, 14.0),
        )


def session(node_id: str, *, expires_in: timedelta = timedelta(minutes=10)) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=f"sess-{node_id}",
        state=NodeSessionState.READY,
        revision=5,
        protocol_major=0,
        protocol_minor=2,
        node_id=node_id,
        principal_id=f"principal-{node_id}",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=datetime.now(timezone.utc) + expires_in,
        negotiated_capabilities=frozenset({"execution_attestation_v1"}),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


def live_node(node_id: str, gpu_memory: int, rpc_port: int, *, session_override=None) -> LiveNodeState:
    captured = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return LiveNodeState(
        session=session_override or session(node_id),
        profile=profile(node_id, gpu_memory=gpu_memory, captured=captured),
        prefill=bench("llama_cpp_prefill", f"{node_id}-p", 3, tps=200.0),
        decode=bench("llama_cpp_decode", f"{node_id}-d", 3, tps=60.0),
        rpc_endpoint=RpcEndpoint("127.0.0.1", rpc_port),
        llama_build_number=999,
        llama_build_commit="abcdef1234567",
    )


def configured_registry(*, control=None, provider=None) -> LiveSharedRuntimeRegistry:
    registry = LiveSharedRuntimeRegistry(placement_provider=provider)
    registry.set_control_client(control or _ControlClient())
    return registry


class LiveSharedRuntimeTests(unittest.TestCase):
    def test_builds_fresh_two_node_plan_without_placement_file(self):
        registry = configured_registry()
        registry.register_node(live_node("node-a", 10_000_000_000, 50051))
        registry.register_node(live_node("node-b", 6_000_000_000, 50052))
        network = bench(
            "tcp_network_path",
            "net-live",
            3,
            local_node_id="node-a",
            peer_node_id="node-b",
            peer_binding="computemesh_ed25519_session_v1",
        )
        registry.register_network_result("node-a", "node-b", network)
        registry.register_model(LiveModelState("test-model", manifest(layer_count=32), Path("/models/model.gguf")))
        live = registry.build_execution_plan("test-model", allow_experimental=True)
        self.assertEqual(live.placement.model_id, "test-model")
        self.assertEqual(live.placement.provider_node_ids, ("node-a", "node-b"))
        self.assertEqual(live.trial_plan.llama_build_number, 999)
        self.assertEqual(live.worker_rpc.text(), "127.0.0.1:50052")
        self.assertTrue(live.trial_plan.bundle_id.startswith("live:"))

    def test_production_provider_receives_full_pool_once_and_selects_pair_privately(self):
        provider = _GlobalProvider()
        registry = configured_registry(control=_ControlClient(("node-a", "node-b", "node-c")), provider=provider)
        registry.register_node(live_node("node-a", 10_000_000_000, 50051))
        registry.register_node(live_node("node-b", 10_000_000_000, 50052))
        registry.register_node(live_node("node-c", 8_000_000_000, 50053))
        for source, target in (("node-a", "node-b"), ("node-b", "node-c"), ("node-c", "node-b")):
            registry.register_network_result(
                source,
                target,
                bench("tcp_network_path", f"{source}-{target}", 3, local_node_id=source, peer_node_id=target),
            )
        registry.register_model(LiveModelState("test-model", manifest(layer_count=32), Path("/models/model.gguf")))
        live = registry.build_execution_plan("test-model", allow_experimental=False)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(provider.calls[0]["candidates"]), 3)
        self.assertEqual(live.placement.provider_node_ids, ("node-b", "node-c"))
        self.assertEqual(live.worker_rpc.text(), "127.0.0.1:50053")

    def test_disconnected_node_is_excluded_before_scheduling(self):
        registry = configured_registry(control=_ControlClient(("node-a",)))
        registry.register_node(live_node("node-a", 10_000_000_000, 50051))
        registry.register_node(live_node("node-b", 6_000_000_000, 50052))
        registry.register_model(LiveModelState("test-model", manifest(layer_count=32), Path("/models/model.gguf")))
        with self.assertRaisesRegex(LiveSharedRuntimeError, "connected"):
            registry.build_execution_plan("test-model", allow_experimental=True)

    def test_expired_session_is_excluded_before_scheduling(self):
        registry = configured_registry()
        registry.register_node(live_node("node-a", 10_000_000_000, 50051))
        registry.register_node(live_node(
            "node-b",
            6_000_000_000,
            50052,
            session_override=session("node-b", expires_in=timedelta(seconds=-1)),
        ))
        registry.register_model(LiveModelState("test-model", manifest(layer_count=32), Path("/models/model.gguf")))
        with self.assertRaisesRegex(LiveSharedRuntimeError, "connected"):
            registry.build_execution_plan("test-model", allow_experimental=True)

    def test_rejects_runtime_build_mismatch(self):
        registry = configured_registry()
        a = live_node("node-a", 10_000_000_000, 50051)
        b = live_node("node-b", 6_000_000_000, 50052)
        b = LiveNodeState(
            session=b.session,
            profile=b.profile,
            prefill=b.prefill,
            decode=b.decode,
            rpc_endpoint=b.rpc_endpoint,
            llama_build_number=1000,
            llama_build_commit=b.llama_build_commit,
        )
        registry.register_node(a)
        registry.register_node(b)
        registry.register_network_result(
            "node-a", "node-b",
            bench("tcp_network_path", "net", 3, local_node_id="node-a", peer_node_id="node-b"),
        )
        registry.register_model(LiveModelState("test-model", manifest(layer_count=32), Path("/models/model.gguf")))
        with self.assertRaises(LiveSharedRuntimeError):
            registry.build_execution_plan("test-model", allow_experimental=True)


if __name__ == "__main__":
    unittest.main()
