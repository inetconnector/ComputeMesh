"""Tests for the repository/server model allowlist and capability selection."""

from __future__ import annotations

import pytest

from services.gateway.model_allowlist import (
    load_model_allowlist,
    model_selection_error,
    reset_model_allowlist_cache,
    select_best_allowed_model,
)


@pytest.fixture(autouse=True)
def _reset_allowlist_cache(monkeypatch: pytest.MonkeyPatch):
    reset_model_allowlist_cache()
    monkeypatch.delenv("COMPUTEMESH_MODEL_ALLOWLIST_URL", raising=False)
    monkeypatch.delenv("COMPUTEMESH_MODEL_ALLOWLIST_SHA256", raising=False)
    yield
    reset_model_allowlist_cache()


def test_noma_mica_is_explicitly_blocked() -> None:
    allowlist = load_model_allowlist(force=True)
    assert allowlist.resolve("noma-mica:latest") is None
    assert "noma-mica:latest" in allowlist.blocked
    assert "noma-mica" in allowlist.blocked


def test_unlisted_runtime_models_are_not_accepted() -> None:
    allowlist = load_model_allowlist(force=True)
    assert allowlist.filter_runtime_ids(["qwen2.5:3b", "noma-mica:latest", "not-approved"]) == ["qwen2.5:3b"]


def test_selection_uses_vram_tiers_and_installed_models() -> None:
    installed = ["qwen2.5:3b", "qwen2.5-coder:14b", "qwen3:32b", "noma-mica:latest"]
    assert select_best_allowed_model(installed, vram_gib=4) == "qwen2.5:3b"
    assert select_best_allowed_model(installed, vram_gib=32) == "qwen2.5-coder:14b"
    assert select_best_allowed_model(installed, vram_gib=64) == "qwen3:32b"


def test_blocked_request_exposes_valid_replacement() -> None:
    error = model_selection_error("noma-mica:latest", installed_ids=["qwen2.5:3b"], vram_gib=4)
    assert "explicitly blocked" in str(error)
    assert error.allowed_models == ["qwen2.5:3b"]  # type: ignore[attr-defined]
    assert error.recommended_model == "qwen2.5:3b"  # type: ignore[attr-defined]
