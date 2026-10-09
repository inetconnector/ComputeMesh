"""Allowlisted NodeOS model preparation for authenticated agent requests."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from protocol.node_session import SessionSnapshot
from services.appliance_dashboard.model_manager import ModelManager, get_model_manager


class ModelPreparationManifestError(RuntimeError):
    """Raised when a local model preparation manifest is invalid or mismatched."""


_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


@dataclass(frozen=True)
class ModelPreparationManifestEntry:
    model_id: str
    repo_id: str
    filename: str
    revision: str
    sha256: str
    size_bytes: int
    layer_count: int
    quantization: str
    license_id: str

    @classmethod
    def from_mapping(cls, model_id: str, raw: Mapping[str, Any]) -> "ModelPreparationManifestEntry":
        if not isinstance(raw, Mapping):
            raise ModelPreparationManifestError("model manifest entry must be an object")
        normalized_id = str(model_id or "")
        repo_id = str(raw.get("repo_id") or "")
        filename = str(raw.get("filename") or "")
        revision = str(raw.get("revision") or raw.get("source_revision") or "")
        digest_match = _DIGEST.fullmatch(str(raw.get("sha256") or raw.get("artifact_digest") or "").lower())
        if not _MODEL_ID.fullmatch(normalized_id):
            raise ModelPreparationManifestError("model manifest contains an invalid model_id")
        if not _REPO_ID.fullmatch(repo_id):
            raise ModelPreparationManifestError("model manifest contains an invalid repo_id")
        if Path(filename).name != filename or not filename.lower().endswith(".gguf"):
            raise ModelPreparationManifestError("model manifest contains an invalid GGUF filename")
        if not _REVISION.fullmatch(revision):
            raise ModelPreparationManifestError("model manifest requires a full 40-character revision")
        if digest_match is None:
            raise ModelPreparationManifestError("model manifest contains an invalid SHA-256 digest")
        try:
            size_bytes = int(raw.get("size_bytes"))
            layer_count = int(raw.get("layer_count"))
        except (TypeError, ValueError) as exc:
            raise ModelPreparationManifestError("model manifest size and layer count must be integers") from exc
        if size_bytes < 1 or layer_count < 2:
            raise ModelPreparationManifestError("model manifest size and layer count are invalid")
        quantization = str(raw.get("quantization") or "")
        license_id = str(raw.get("license_id") or "")
        if not 1 <= len(quantization) <= 64 or not 1 <= len(license_id) <= 256:
            raise ModelPreparationManifestError("model manifest quantization and license are required")
        return cls(
            model_id=normalized_id,
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            sha256=digest_match.group(1),
            size_bytes=size_bytes,
            layer_count=layer_count,
            quantization=quantization,
            license_id=license_id,
        )

    def matches_request(self, payload: Mapping[str, Any]) -> bool:
        requested_digest = str(payload.get("artifact_digest") or "").lower().removeprefix("sha256:")
        return (
            str(payload.get("model_id") or "") == self.model_id
            and requested_digest == self.sha256
            and int(payload.get("size_bytes") or 0) == self.size_bytes
        )


class AllowlistedModelPreparationExecutor:
    """Prepare only entries present in a local operator-supplied manifest."""

    def __init__(
        self,
        entries: Mapping[str, ModelPreparationManifestEntry],
        *,
        manager: ModelManager | None = None,
    ) -> None:
        if not entries or len(entries) > 512:
            raise ModelPreparationManifestError("model preparation manifest must contain 1..512 entries")
        self.entries = dict(entries)
        self.manager = manager or get_model_manager()
        self._lock = RLock()

    @classmethod
    def from_mapping(
        cls,
        document: Mapping[str, Any],
        *,
        manager: ModelManager | None = None,
    ) -> "AllowlistedModelPreparationExecutor":
        if not isinstance(document, Mapping) or document.get("schema_version") != 1:
            raise ModelPreparationManifestError("model preparation manifest must use schema_version 1")
        raw_models = document.get("models")
        if not isinstance(raw_models, Mapping):
            raise ModelPreparationManifestError("model preparation manifest requires a models object")
        entries = {
            str(model_id): ModelPreparationManifestEntry.from_mapping(str(model_id), raw)
            for model_id, raw in raw_models.items()
        }
        return cls(entries, manager=manager)

    @classmethod
    def from_path(cls, path: str | Path, *, manager: ModelManager | None = None) -> "AllowlistedModelPreparationExecutor":
        manifest_path = Path(path)
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ModelPreparationManifestError("model preparation manifest does not exist")
        if manifest_path.stat().st_size > 2 * 1024 * 1024:
            raise ModelPreparationManifestError("model preparation manifest is too large")
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ModelPreparationManifestError("model preparation manifest is not valid JSON") from exc
        return cls.from_mapping(document, manager=manager)

    def __call__(self, _session: SessionSnapshot, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        model_id = str(payload.get("model_id") or "")
        entry = self.entries.get(model_id)
        if entry is None:
            raise ModelPreparationManifestError("requested model is not in the local preparation manifest")
        if not entry.matches_request(payload):
            raise ModelPreparationManifestError("requested model does not match the approved manifest digest or size")
        with self._lock:
            for installed in self.manager.list_models():
                installed_digest = str(installed.get("sha256") or "").lower().removeprefix("sha256:")
                if installed.get("model_id") == entry.model_id and installed_digest == entry.sha256:
                    if not bool(installed.get("present")):
                        raise ModelPreparationManifestError("catalogued model artifact is missing")
                    return {"status": "available", "reason_code": "model_already_installed", "idempotency_replay": True}
            result = self.manager.install_from_hugging_face(
                model_id=entry.model_id,
                repo_id=entry.repo_id,
                filename=entry.filename,
                revision=entry.revision,
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
                layer_count=entry.layer_count,
                quantization=entry.quantization,
                license_id=entry.license_id,
            )
        returned_digest = str(result.get("sha256") or "").lower().removeprefix("sha256:")
        if returned_digest != entry.sha256:
            raise ModelPreparationManifestError("model manager returned a digest mismatch")
        return {"status": "prepared", "reason_code": "downloaded_and_verified"}


__all__ = [
    "AllowlistedModelPreparationExecutor",
    "ModelPreparationManifestEntry",
    "ModelPreparationManifestError",
]
