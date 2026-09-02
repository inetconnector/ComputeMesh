from __future__ import annotations

from pathlib import Path

import pytest

from runtime.llama.gpu_promo_challenge import (
    GpuPromoChallengeConfig,
    infer_gpu_promo_backend,
    normalize_gpu_promo_backend,
    validate_local_llama_device,
)


def _files(tmp_path: Path) -> tuple[Path, Path]:
    llama = tmp_path / "llama-server"
    model = tmp_path / "probe.gguf"
    llama.write_bytes(b"runtime")
    model.write_bytes(b"GGUF")
    return llama, model


@pytest.mark.parametrize(
    ("device", "backend"),
    [
        ("CUDA0", "cuda"),
        ("ROCm0", "rocm"),
        ("HIP0", "rocm"),
        ("Vulkan0", "vulkan"),
        ("Vulkan17", "vulkan"),
    ],
)
def test_backend_is_inferred_from_local_llama_device(
    tmp_path: Path, device: str, backend: str
) -> None:
    llama, model = _files(tmp_path)
    config = GpuPromoChallengeConfig(
        llama_server=llama,
        model=model,
        device=device,
        accelerator_id="stable-gpu-id",
    )
    assert config.device == device
    assert config.runtime_backend == backend


def test_backend_aliases_are_normalized() -> None:
    assert normalize_gpu_promo_backend("HIP") == "rocm"
    assert normalize_gpu_promo_backend("AMD") == "rocm"
    assert normalize_gpu_promo_backend("NVIDIA") == "cuda"


@pytest.mark.parametrize("device", ["CPU", "RPC0", "none", "CUDA0;rm", "Vulkan 0", ""])
def test_promo_device_rejects_cpu_rpc_and_unsafe_values(device: str) -> None:
    with pytest.raises(ValueError):
        validate_local_llama_device(device)


def test_unknown_local_gpu_namespace_fails_closed() -> None:
    with pytest.raises(ValueError, match="cannot infer"):
        infer_gpu_promo_backend("MysteryGPU0")


def test_explicit_backend_can_support_nonstandard_safe_device_names(tmp_path: Path) -> None:
    llama, model = _files(tmp_path)
    config = GpuPromoChallengeConfig(
        llama_server=llama,
        model=model,
        device="AMD-GFX1100",
        accelerator_id="pci-0000:03:00.0",
        runtime_backend="vulkan",
    )
    assert config.device == "AMD-GFX1100"
    assert config.runtime_backend == "vulkan"
