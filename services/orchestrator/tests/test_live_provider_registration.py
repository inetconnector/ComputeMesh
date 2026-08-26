from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from protocol.control import ControlEnvelope
from protocol.node_session import NodeSessionState, SessionSnapshot
from protocol.session_contracts import SessionMessageContractValidator
from services.orchestrator.live_provider_registration import LiveProviderRegistration
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry


NOW = datetime.now(timezone.utc)


def session(state=NodeSessionState.PROFILE_SYNCED, revision=4):
    return SessionSnapshot(
        session_id="session-a",
        state=state,
        revision=revision,
        protocol_major=0,
        protocol_minor=2,
        node_id="node-a",
        principal_id="provider-a",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=NOW + timedelta(minutes=10),
        negotiated_capabilities=frozenset({"execution_attestation_v1", "live_runtime_registration_v1"}),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


def envelope(message_type, payload, snapshot=None):
    snap = snapshot or session()
    return ControlEnvelope(
        protocol_major=0,
        protocol_minor=2,
        message_type=message_type,
        request_id=f"req-{message_type}",
        correlation_id=snap.session_id,
        actor_id="node-a",
        target_id="cp",
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        expected_revision=snap.revision,
        payload=payload,
    )


def profile():
    return {
        "schema_version": 1,
        "node_id": "node-a",
        "profile_revision": 3,
        "captured_at": NOW.isoformat().replace("+00:00", "Z"),
        "platform": {"os": "Linux", "release": "1", "architecture": "x86_64"},
        "cpu": {"model": "CPU", "logical_cores": 8},
        "memory": {"total_bytes": 16_000_000_000, "available_bytes": 12_000_000_000},
        "devices": [{"device_id": "gpu:0", "kind": "gpu", "vendor": "NVIDIA", "name": "GPU", "memory_total_bytes": 12_000_000_000}],
        "runtime_capabilities": [{"runtime": "llama.cpp", "version": "1"}],
        "provider_limits": {"draining": False, "max_memory_fraction": 0.9, "max_power_watts": None},
        "benchmark_refs": [],
    }


def benchmark(name):
    metrics = {"model_name": "model.gguf", "model_size_bytes": 8_000_000_000}
    if name == "llama_cpp_prefill":
        metrics.update({"prefill_tokens_per_second_avg": 100.0, "prompt_tokens": 512})
    else:
        metrics.update({"decode_tokens_per_second_avg": 30.0, "generated_tokens": 128})
    return {
        "schema_version": 1,
        "run_id": f"run-{name}",
        "benchmark_name": name,
        "captured_at": NOW.isoformat().replace("+00:00", "Z"),
        "profile_revision": 3,
        "conditions": {"warm_state": "warm"},
        "metrics": metrics,
        "raw_samples": [],
    }


class LiveProviderRegistrationTests(unittest.TestCase):
    def test_runtime_advertisement_contract(self):
        payload = {
            "schema_version": 1,
            "node_id": "node-a",
            "profile_revision": 3,
            "runtime": "llama.cpp",
            "llama_build_commit": "abcdef1",
            "llama_build_number": 123,
            "rpc": {"host": "10.0.0.2", "port": 50052},
        }
        SessionMessageContractValidator().validate("RuntimeAdvertisement", payload)

    def test_profile_runtime_and_benchmarks_publish_schedulable_node(self):
        registry = LiveSharedRuntimeRegistry()
        registration = LiveProviderRegistration(registry)
        snap = session()
        registration.note_session(snap)
        registration.consume(envelope("NodeProfileUpdate", profile(), snap), snap)
        runtime = {
            "schema_version": 1,
            "node_id": "node-a",
            "profile_revision": 3,
            "runtime": "llama.cpp",
            "llama_build_commit": "abcdef1",
            "llama_build_number": 123,
            "rpc": {"host": "10.0.0.2", "port": 50052},
        }
        registration.consume(envelope("RuntimeAdvertisement", runtime, snap), snap)
        registration.consume(envelope("BenchmarkReport", benchmark("llama_cpp_prefill"), snap), snap)
        with self.assertRaises(KeyError):
            registry.get_session("node-a")
        registration.consume(envelope("BenchmarkReport", benchmark("llama_cpp_decode"), snap), snap)
        self.assertEqual(registry.get_session("node-a").session_id, "session-a")

    def test_runtime_advertisement_must_match_profile_revision(self):
        registry = LiveSharedRuntimeRegistry()
        registration = LiveProviderRegistration(registry)
        snap = session()
        registration.note_session(snap)
        registration.consume(envelope("NodeProfileUpdate", profile(), snap), snap)
        runtime = {
            "schema_version": 1,
            "node_id": "node-a",
            "profile_revision": 99,
            "runtime": "llama.cpp",
            "llama_build_commit": "abcdef1",
            "llama_build_number": 123,
            "rpc": {"host": "10.0.0.2", "port": 50052},
        }
        with self.assertRaises(Exception):
            registration.consume(envelope("RuntimeAdvertisement", runtime, snap), snap)


if __name__ == "__main__":
    unittest.main()
