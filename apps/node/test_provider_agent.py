from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apps.node.provider_agent import ProviderAgent, _runtime_document
from protocol.session_contracts import SessionMessageContractValidator


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
    key_path = tmp_path / "node.pem"
    _write_key(key_path)
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
    )
    assert agent.key_id.startswith("ed25519:")
    assert agent.profile["node_id"] == "node-a"
