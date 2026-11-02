from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from apps.node.provider_agent_any_gpu import _gpu_promo_runner_from_args


def _args(tmp_path: Path, *, device: str) -> Namespace:
    llama = tmp_path / "llama-server"
    model = tmp_path / "probe.gguf"
    llama.write_bytes(b"runtime")
    model.write_bytes(b"GGUF")
    return Namespace(
        promo_llama_server=llama,
        promo_model=model,
        promo_device=device,
        promo_accelerator_id="pci-0000:03:00.0",
        promo_port=18090,
        promo_ctx_size=2048,
        promo_max_timeout=60.0,
    )


def test_rocm_backend_can_be_selected_for_nonstandard_amd_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COMPUTEMESH_PROMO_BACKEND", "rocm")
    runner = _gpu_promo_runner_from_args(_args(tmp_path, device="AMD-GFX1100"))
    assert runner is not None
    assert runner.config.runtime_backend == "rocm"
    assert runner.config.device == "AMD-GFX1100"


def test_vulkan_backend_can_be_selected_for_any_safe_gpu_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COMPUTEMESH_PROMO_BACKEND", "vulkan")
    runner = _gpu_promo_runner_from_args(_args(tmp_path, device="AMD-legacy-0"))
    assert runner is not None
    assert runner.config.runtime_backend == "vulkan"


def test_invalid_backend_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COMPUTEMESH_PROMO_BACKEND", "cpu")
    with pytest.raises(ValueError):
        _gpu_promo_runner_from_args(_args(tmp_path, device="AMD-GFX1100"))
