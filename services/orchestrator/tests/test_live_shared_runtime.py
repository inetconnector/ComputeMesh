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
from services.scheduler.tests.test_placement import bench, manifest, profile


def session(node_id: str) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=f"sess-{node_id}",
        state=NodeSessionState.READY,
        revision=5,
        protocol_major=0,
        protocol_minor=2,
        node_id=node_id,
        principal_id=f"principal-{node_id}",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        negotiated_capabilities=frozenset({"execution_attestation_v1"}),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


def live_node(node_id: str, gpu_memory: int, rpc_port: int) -> LiveNodeState:
    captured = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return LiveNodeState(
        session=session(node_id),
        profile=profile(node_id, gpu_memory=gpu_memory, captured=captured),
        prefill=bench("llama_cpp_prefill", f"{node_id}-p", 3, tps=200.0),
        decode=bench("llama_cpp_decode", f"{node_id}-d", 3, tps=60.0),
        rpc_endpoint=RpcEndpoint("127.0.0.1", rpc_port),
        llama_build_number=999,
        llama_build_commit="abcdef1234567",
    )


class LiveSharedRuntimeTests(unittest.TestCase):
    def test_builds_fresh_two_node_plan_without_placement_file(self):
        registry = LiveSharedRuntimeRegistry()
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
        registry.register_model(
            LiveModelState(
                model_id="test-model",
                manifest=manifest(layer_count=32),
                model_path=Path("/models/model.gguf"),
            )
        )
        live = registry.build_execution_plan("test-model", allow_experimental=True)
        self.assertEqual(live.placement.model_id, "test-model")
        self.assertEqual(live.placement.provider_node_ids, ("node-a", "node-b"))
        self.assertEqual(live.trial_plan.llama_build_number, 999)
        self.assertEqual(live.worker_rpc.text(), "127.0.0.1:50052")
        self.assertTrue(live.trial_plan.bundle_id.startswith("live:"))

    def test_rejects_runtime_build_mismatch(self):
        registry = LiveSharedRuntimeRegistry()
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
