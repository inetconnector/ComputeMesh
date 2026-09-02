from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apps.node.provider_agent import ProviderAgent, ProviderAgentError, _runtime_document
from protocol.node_session import NodeSessionState, SessionSnapshot
from protocol.session_contracts import SessionMessageContractValidator
from runtime.llama.gpu_promo_challenge import (
    GPU_PROMO_CAPABILITY,
    GpuPromoWorkResult,
)


def _profile(node_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "node_id": node_id,
        "profile_revision": 3,
        "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "platform": {"os": "Linux", "release": "1", "architecture": "x86_64"},
        "cpu": {"model": "CPU", "logical_cores": 8},
        "memory": {"total_bytes": 16_000_000_000, "available_bytes": 12_000_000_000},
        "devices": [
            {
                "device_id": "gpu:0",
                "kind": "gpu",
                "vendor": "NVIDIA",
                "name": "GPU",
                "memory_total_bytes": 12_000_000_000,
            }
        ],
        "runtime_capabilities": [{"runtime": "llama.cpp", "version": "1"}],
        "provider_limits": {
            "draining": False,
            "max_memory_fraction": 0.9,
            "max_power_watts": None,
        },
        "benchmark_refs": [],
    }


def _benchmark(name: str) -> dict[str, object]:
    metrics: dict[str, object] = {"model_name": "model.gguf", "model_size_bytes": 8_000_000_000}
    if name == "llama_cpp_prefill":
        metrics.update({"prefill_tokens_per_second_avg": 100.0, "prompt_tokens": 512})
    else:
        metrics.update({"decode_tokens_per_second_avg": 30.0, "generated_tokens": 128})
    return {
        "schema_version": 1,
        "run_id": f"run-{name}",
        "benchmark_name": name,
        "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "profile_revision": 3,
        "conditions": {"warm_state": "warm"},
        "metrics": metrics,
        "raw_samples": [],
    }


def _write_key(path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def _agent(tmp_path: Path, *, gpu_promo_runner: object | None = None) -> ProviderAgent:
    key_path = tmp_path / "node.pem"
    _write_key(key_path)
    return ProviderAgent(
        node_id="node-a",
        private_key_path=key_path,
        profile=_profile("node-a"),
        prefill=_benchmark("llama_cpp_prefill"),
        decode=_benchmark("llama_cpp_decode"),
        runtime_advertisement=_runtime_document(
            node_id="node-a",
            profile_revision=3,
            rpc_host="10.0.0.2",
            rpc_port=50052,
            build_number=123,
            build_commit="abcdef1",
        ),
        gpu_promo_runner=gpu_promo_runner,  # type: ignore[arg-type]
    )


def _session(agent: ProviderAgent) -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-a",
        state=NodeSessionState.READY,
        revision=7,
        protocol_major=1,
        protocol_minor=0,
        node_id="node-a",
        principal_id="provider-a",
        auth_method="ed25519_challenge_v1",
        credential_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        negotiated_capabilities=frozenset(agent.capabilities),
        profile_revision=3,
        drain_reason=None,
        close_reason=None,
    )


def _assert_provider_error(fragment: str, call: object) -> None:
    try:
        call()  # type: ignore[operator]
    except ProviderAgentError as exc:
        assert fragment in str(exc)
    else:
        raise AssertionError(f"expected ProviderAgentError containing {fragment!r}")


def test_runtime_advertisement_matches_public_contract() -> None:
    doc = _runtime_document(
        node_id="node-a",
        profile_revision=3,
        rpc_host="10.0.0.2",
        rpc_port=50052,
        build_number=123,
        build_commit="abcdef1",
    )
    SessionMessageContractValidator().validate("RuntimeAdvertisement", doc)


def test_provider_agent_binds_profile_benchmarks_runtime_and_key(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    assert agent.key_id.startswith("ed25519:")
    assert agent.profile["node_id"] == "node-a"
    assert agent.capacity_guard.node_id == "node-a"
    assert agent.capacity_guard.get_status()["available_slots"] == 1
    assert GPU_PROMO_CAPABILITY not in agent.capabilities


def test_provider_agent_accepts_custom_capacity_guard(tmp_path: Path) -> None:
    from runtime.capacity_guard import LocalCapacityGuard

    key_path = tmp_path / "node.pem"
    _write_key(key_path)
    custom_guard = LocalCapacityGuard(node_id="node-a", max_concurrent_jobs=4, total_memory_mb=32768)
    agent = ProviderAgent(
        node_id="node-a",
        private_key_path=key_path,
        profile=_profile("node-a"),
        prefill=_benchmark("llama_cpp_prefill"),
        decode=_benchmark("llama_cpp_decode"),
        runtime_advertisement=_runtime_document(
            node_id="node-a",
            profile_revision=3,
            rpc_host="10.0.0.2",
            rpc_port=50052,
            build_number=123,
            build_commit="abcdef1",
        ),
        capacity_guard=custom_guard,
    )
    assert agent.capacity_guard is custom_guard
    assert agent.capacity_guard.get_status()["max_concurrent_jobs"] == 4


class _GpuRunner:
    def run(self, challenge: dict[str, object]) -> GpuPromoWorkResult:
        assert challenge["challenge_id"] == "promo_ch_abc"
        return GpuPromoWorkResult(
            accelerator_id="GPU-uuid-a",
            runtime_backend="cuda",
            runtime_build="llama.cpp:123:abcdef1;model_sha256:" + "2" * 64 + ";device:CUDA0",
            work_digest="sha256:" + "3" * 64,
            elapsed_ms=15.25,
        )


def _gpu_request(agent: ProviderAgent) -> dict[str, object]:
    return {
        "session_id": "session-a",
        "session_revision": 7,
        "challenge": {
            "schema_version": 1,
            "challenge_id": "promo_ch_abc",
            "claim_class": "gpu_onboarding",
            "owner_id": "owner-a",
            "node_id": "node-a",
            "key_id": agent.key_id,
            "hardware_claim_id": "cmhw_v1_test",
            "evidence_digest": "sha256:" + "1" * 64,
            "nonce": "n" * 32,
            "prompt": "ComputeMesh GPU promo deterministic probe",
            "seed": 7,
            "n_predict": 16,
            "model_sha256": "2" * 64,
            "expected_llama_build_number": 123,
            "expected_llama_build_commit": "abcdef1",
            "timeout_ms": 30000,
        },
    }


def test_provider_agent_signs_gpu_promo_result_with_enrolled_node_key(tmp_path: Path) -> None:
    agent = _agent(tmp_path, gpu_promo_runner=_GpuRunner())
    assert GPU_PROMO_CAPABILITY in agent.capabilities
    response = agent.handle_request("GpuPromoChallengeRequest", _gpu_request(agent), _session(agent))
    SessionMessageContractValidator().validate("GpuPromoChallengeResponse", response)
    assert response["key_id"] == agent.key_id
    proof = response["proof"]
    assert proof["node_id"] == "node-a"
    assert proof["key_id"] == agent.key_id
    assert proof["work_digest"] == "sha256:" + "3" * 64


def test_provider_agent_rejects_gpu_request_when_feature_not_configured(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    request = _gpu_request(agent)
    session = _session(agent)
    session = SessionSnapshot(
        **{**session.__dict__, "negotiated_capabilities": frozenset({GPU_PROMO_CAPABILITY})}
    )
    _assert_provider_error(
        "not enabled",
        lambda: agent.handle_request("GpuPromoChallengeRequest", request, session),
    )


def test_provider_agent_rejects_gpu_request_for_another_key(tmp_path: Path) -> None:
    agent = _agent(tmp_path, gpu_promo_runner=_GpuRunner())
    request = _gpu_request(agent)
    challenge = dict(request["challenge"])
    challenge["key_id"] = "ed25519:other-key"
    request["challenge"] = challenge
    _assert_provider_error(
        "another node key",
        lambda: agent.handle_request("GpuPromoChallengeRequest", request, _session(agent)),
    )
