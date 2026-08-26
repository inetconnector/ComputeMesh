"""Validated live model catalog for ComputeMesh shared serving."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from services.orchestrator.live_shared_runtime import LiveModelState, LiveSharedRuntimeError

ROOT = Path(__file__).resolve().parents[2]
MODEL_SCHEMA = ROOT / "protocol" / "schemas" / "model_manifest.schema.json"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MODEL_BYTES = 1024 * 1024 * 1024 * 1024


class LiveModelCatalogError(LiveSharedRuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise LiveModelCatalogError("model manifest must be a regular file")
    size = path.stat().st_size
    if not (0 < size <= MAX_MANIFEST_BYTES):
        raise LiveModelCatalogError("model manifest size is invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveModelCatalogError("model manifest must contain UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise LiveModelCatalogError("model manifest root must be an object")
    return value


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


def _artifact_record(manifest: dict[str, Any]) -> dict[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict):
        raise LiveModelCatalogError("live shared serving currently requires exactly one model artifact")
    artifact = dict(artifacts[0])
    if artifact.get("format") != "gguf":
        raise LiveModelCatalogError("live shared serving requires a GGUF artifact")
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


def load_verified_live_model(*, manifest_path: Path, model_root: Path) -> LiveModelState:
    manifest_path = manifest_path.resolve(strict=True)
    root = model_root.resolve(strict=True)
    manifest = _load_json(manifest_path)
    _validate_manifest(manifest)
    artifact = _artifact_record(manifest)
    filename = artifact.get("filename")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise LiveModelCatalogError("artifact filename must be a plain basename")
    model_path = (root / filename).resolve(strict=True)
    try:
        model_path.relative_to(root)
    except ValueError as exc:
        raise LiveModelCatalogError("model artifact escapes configured model root") from exc
    if model_path.is_symlink() or not model_path.is_file():
        raise LiveModelCatalogError("model artifact must be a regular non-symlink file")
    size = model_path.stat().st_size
    if size <= 0 or size > MAX_MODEL_BYTES:
        raise LiveModelCatalogError("model artifact size is invalid")
    expected_size = artifact.get("size_bytes")
    if expected_size is not None and int(expected_size) != size:
        raise LiveModelCatalogError("model artifact size does not match manifest")
    digest = _sha256_file(model_path)
    expected_digest = str(artifact.get("sha256", "")).lower().removeprefix("sha256:")
    if digest != expected_digest:
        raise LiveModelCatalogError("model artifact SHA-256 does not match manifest")
    model_id = manifest.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise LiveModelCatalogError("model manifest lacks model_id")
    return LiveModelState(model_id=model_id, manifest=manifest, model_path=model_path)


def discover_verified_live_models(*, manifest_dir: Path, model_root: Path) -> tuple[LiveModelState, ...]:
    directory = manifest_dir.resolve(strict=True)
    if not directory.is_dir():
        raise LiveModelCatalogError("model manifest path must be a directory")
    states: list[LiveModelState] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.computemesh-model-manifest.json")):
        state = load_verified_live_model(manifest_path=path, model_root=model_root)
        if state.model_id in seen:
            raise LiveModelCatalogError(f"duplicate model_id {state.model_id!r}")
        seen.add(state.model_id)
        states.append(state)
    if not states:
        raise LiveModelCatalogError("no verified model manifests were discovered")
    return tuple(states)


def register_verified_live_models(registry: Any, *, manifest_dir: Path, model_root: Path) -> tuple[str, ...]:
    states = discover_verified_live_models(manifest_dir=manifest_dir, model_root=model_root)
    for state in states:
        registry.register_model(state)
    return tuple(state.model_id for state in states)
