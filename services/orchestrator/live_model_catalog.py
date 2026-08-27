"""Validated live model catalog for ComputeMesh shared serving."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from services.compliance.policy import require_production_model_attribution
from services.orchestrator.live_shared_runtime import LiveModelState, LiveSharedRuntimeError

ROOT = Path(__file__).resolve().parents[2]
MODEL_SCHEMA = ROOT / "protocol" / "schemas" / "model_manifest.schema.json"
MAX_JSON_BYTES = 1024 * 1024
MAX_MODEL_BYTES = 1024 * 1024 * 1024 * 1024


class LiveModelCatalogError(LiveSharedRuntimeError):
    pass


def _load_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise LiveModelCatalogError("catalog/manifest must be a regular non-symlink file")
    size = path.stat().st_size
    if not (0 < size <= MAX_JSON_BYTES):
        raise LiveModelCatalogError("catalog/manifest size is invalid")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveModelCatalogError("catalog/manifest must contain UTF-8 JSON") from exc


def _validate_manifest(manifest: dict[str, Any]) -> None:
    schema = json.loads(MODEL_SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "$"
        raise LiveModelCatalogError(f"model manifest invalid at {where}: {first.message}")
    runtimes = manifest.get("runtime_compatibility") or []
    if not any(isinstance(item, dict) and item.get("runtime") == "llama.cpp" for item in runtimes):
        raise LiveModelCatalogError("model manifest is not compatible with llama.cpp")
    partitioning = manifest.get("partitioning") or {}
    if "contiguous_layers" not in partitioning.get("allowed", []):
        raise LiveModelCatalogError("model manifest does not permit contiguous layer partitioning")
    if not isinstance(manifest.get("layer_count"), int):
        raise LiveModelCatalogError("live shared serving requires manifest layer_count")
    require_production_model_attribution(manifest)


def _artifact_record(manifest: dict[str, Any]) -> dict[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict):
        raise LiveModelCatalogError("live shared serving currently requires exactly one model artifact")
    artifact = dict(artifacts[0])
    media_type = str(artifact.get("media_type", ""))
    if media_type and media_type not in {"application/x-gguf", "application/octet-stream"}:
        raise LiveModelCatalogError("live shared serving requires a GGUF-compatible artifact")
    return artifact


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_beneath(root: Path, relative: str, *, label: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise LiveModelCatalogError(f"{label} must be a relative path")
    resolved = (root / relative).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LiveModelCatalogError(f"{label} escapes configured root") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise LiveModelCatalogError(f"{label} must be a regular non-symlink file")
    return resolved


def load_verified_live_model(*, manifest_path: Path, artifact_path: Path) -> LiveModelState:
    manifest_path = manifest_path.resolve(strict=True)
    artifact_path = artifact_path.resolve(strict=True)
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise LiveModelCatalogError("model manifest root must be an object")
    _validate_manifest(manifest)
    artifact = _artifact_record(manifest)
    if artifact_path.is_symlink() or not artifact_path.is_file():
        raise LiveModelCatalogError("model artifact must be a regular non-symlink file")
    size = artifact_path.stat().st_size
    if size <= 0 or size > MAX_MODEL_BYTES:
        raise LiveModelCatalogError("model artifact size is invalid")
    with artifact_path.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            raise LiveModelCatalogError("model artifact does not have GGUF magic")
    if int(artifact["size_bytes"]) != size:
        raise LiveModelCatalogError("model artifact size does not match manifest")
    digest = _sha256_file(artifact_path)
    expected_digest = str(artifact["digest"]).lower().removeprefix("sha256:")
    if digest != expected_digest:
        raise LiveModelCatalogError("model artifact SHA-256 does not match manifest")
    model_id = str(manifest["model_id"])
    return LiveModelState(model_id=model_id, manifest=manifest, model_path=artifact_path)


def discover_verified_live_models(*, catalog_path: Path, catalog_root: Path) -> tuple[LiveModelState, ...]:
    root = catalog_root.resolve(strict=True)
    if not root.is_dir():
        raise LiveModelCatalogError("model catalog root must be a directory")
    catalog = _load_json(catalog_path.resolve(strict=True))
    if not isinstance(catalog, dict) or set(catalog) != {"schema_version", "models"} or catalog.get("schema_version") != 1:
        raise LiveModelCatalogError("invalid live model catalog envelope")
    entries = catalog.get("models")
    if not isinstance(entries, list) or not entries or len(entries) > 256:
        raise LiveModelCatalogError("live model catalog must contain 1..256 models")
    states: list[LiveModelState] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"manifest", "artifact"}:
            raise LiveModelCatalogError("invalid live model catalog entry")
        manifest = _resolve_beneath(root, str(entry["manifest"]), label="manifest path")
        artifact = _resolve_beneath(root, str(entry["artifact"]), label="artifact path")
        state = load_verified_live_model(manifest_path=manifest, artifact_path=artifact)
        if state.model_id in seen:
            raise LiveModelCatalogError(f"duplicate model_id {state.model_id!r}")
        seen.add(state.model_id)
        states.append(state)
    return tuple(states)


def register_verified_live_models(registry: Any, *, catalog_path: Path, catalog_root: Path) -> tuple[str, ...]:
    states = discover_verified_live_models(catalog_path=catalog_path, catalog_root=catalog_root)
    for state in states:
        registry.register_model(state)
    return tuple(state.model_id for state in states)
