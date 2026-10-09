from __future__ import annotations

import pytest
from apps.node.model_preparation import (
    AllowlistedModelPreparationExecutor,
    ModelPreparationManifestError,
)

_DIGEST = "a" * 64


class _Manager:
    def __init__(self, installed=None):
        self.installed = list(installed or [])
        self.calls = []

    def list_models(self):
        return list(self.installed)

    def install_from_hugging_face(self, **kwargs):
        self.calls.append(kwargs)
        return {"model_id": kwargs["model_id"], "sha256": kwargs["sha256"]}


def _manifest():
    return {
        "schema_version": 1,
        "models": {
            "org/model-q4": {
                "repo_id": "org/model-gguf",
                "filename": "model-q4.gguf",
                "revision": "b" * 40,
                "sha256": _DIGEST,
                "size_bytes": 100,
                "layer_count": 32,
                "quantization": "Q4_K_M",
                "license_id": "apache-2.0",
            }
        },
    }


def _request():
    return {
        "model_id": "org/model-q4",
        "artifact_digest": f"sha256:{_DIGEST}",
        "size_bytes": 100,
    }


def test_allowlisted_executor_installs_exact_manifest_entry():
    manager = _Manager()
    executor = AllowlistedModelPreparationExecutor.from_mapping(_manifest(), manager=manager)
    result = executor(None, _request())
    assert result == {"status": "prepared", "reason_code": "downloaded_and_verified"}
    assert manager.calls[0]["revision"] == "b" * 40
    assert manager.calls[0]["sha256"] == _DIGEST


def test_allowlisted_executor_replays_installed_digest_without_redownload():
    manager = _Manager([{"model_id": "org/model-q4", "sha256": _DIGEST, "present": True}])
    executor = AllowlistedModelPreparationExecutor.from_mapping(_manifest(), manager=manager)
    result = executor(None, _request())
    assert result["status"] == "available"
    assert manager.calls == []


def test_allowlisted_executor_rejects_digest_or_size_drift():
    executor = AllowlistedModelPreparationExecutor.from_mapping(_manifest(), manager=_Manager())
    with pytest.raises(ModelPreparationManifestError, match="digest or size"):
        executor(None, {**_request(), "size_bytes": 101})
    with pytest.raises(ModelPreparationManifestError, match="not in the local"):
        executor(None, {**_request(), "model_id": "other/model"})


def test_allowlisted_manifest_requires_pinned_source_revision():
    document = _manifest()
    document["models"]["org/model-q4"]["revision"] = "main"
    with pytest.raises(ModelPreparationManifestError, match="40-character"):
        AllowlistedModelPreparationExecutor.from_mapping(document, manager=_Manager())
