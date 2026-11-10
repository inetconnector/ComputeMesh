"""Authoritative ComputeMesh model allowlist and capability-aware selection.

The repository mirror is the development source of truth.  A configured HTTPS
master URL can replace it at runtime.  Unlisted or explicitly blocked models
are never advertised or selected.  This module only selects models that are
already installed or otherwise exposed by the runtime; verified model
preparation remains a separate operation.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


class ModelAllowlistError(ValueError):
    """Raised when the authoritative model allowlist is invalid or unavailable."""


_MAX_BYTES = 2 * 1024 * 1024
_CACHE_TTL_SECONDS = 15.0
_CACHE: tuple[float, "ModelAllowlist"] | None = None
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _ROOT / "config" / "model_allowlist.json"


@dataclass(frozen=True)
class AllowedModel:
    model_id: str
    aliases: tuple[str, ...]
    source: str
    license: str
    license_status: str
    min_vram_gib: float
    storage_gib: float
    priority: int
    enabled: bool
    capabilities: tuple[str, ...]
    distributed_only: bool = False
    min_nodes: int = 1


def _read_json_bytes(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > _MAX_BYTES:
        raise ModelAllowlistError("model allowlist size is invalid")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelAllowlistError("model allowlist is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ModelAllowlistError("model allowlist root must be an object")
    return document


def _validate(document: dict[str, Any]) -> "ModelAllowlist":
    if document.get("schema_version") != 1:
        raise ModelAllowlistError("unsupported model allowlist schema")
    version = str(document.get("allowlist_version", "")).strip()
    if not version:
        raise ModelAllowlistError("model allowlist version is required")
    expires_at = str(document.get("expires_at", "")).strip()
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelAllowlistError("model allowlist expiry is invalid") from exc
    if expires.tzinfo is None or expires.astimezone(UTC) <= datetime.now(UTC):
        if os.environ.get("COMPUTEMESH_ALLOW_EXPIRED_MODEL_ALLOWLIST", "") not in {"1", "true", "TRUE"}:
            raise ModelAllowlistError("model allowlist has expired")

    raw_blocked = document.get("blocked_model_ids", [])
    if not isinstance(raw_blocked, list) or not all(isinstance(item, str) for item in raw_blocked):
        raise ModelAllowlistError("blocked_model_ids must be a string list")
    blocked = {item.strip().lower() for item in raw_blocked if item.strip()}
    raw_models = document.get("models")
    if not isinstance(raw_models, list) or not raw_models or len(raw_models) > 512:
        raise ModelAllowlistError("model allowlist must contain 1..512 models")
    entries: dict[str, AllowedModel] = {}
    aliases: dict[str, str] = {}
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise ModelAllowlistError("model allowlist entry must be an object")
        model_id = str(raw.get("id", "")).strip()
        if not model_id or len(model_id) > 256:
            raise ModelAllowlistError("model allowlist entry has an invalid id")
        key = model_id.lower()
        if key in entries or key in blocked:
            raise ModelAllowlistError(f"duplicate or blocked allowlist model: {model_id}")
        raw_aliases = raw.get("aliases", [])
        if not isinstance(raw_aliases, list) or not all(isinstance(item, str) for item in raw_aliases):
            raise ModelAllowlistError(f"aliases are invalid for {model_id}")
        try:
            min_vram = float(raw.get("min_vram_gib", 0))
            storage = float(raw.get("storage_gib", 0))
            priority = int(raw.get("priority", 0))
            min_nodes = int(raw.get("min_nodes", 1))
        except (TypeError, ValueError) as exc:
            raise ModelAllowlistError(f"resource metadata is invalid for {model_id}") from exc
        if min_vram <= 0 or storage <= 0 or priority < 0 or min_nodes < 1:
            raise ModelAllowlistError(f"resource metadata is out of bounds for {model_id}")
        license_status = str(raw.get("license_status", "")).strip()
        enabled = bool(raw.get("enabled", False))
        if enabled and license_status != "verified":
            raise ModelAllowlistError(f"enabled model lacks verified license status: {model_id}")
        entry = AllowedModel(
            model_id=model_id,
            aliases=tuple(str(item).strip() for item in raw_aliases if str(item).strip()),
            source=str(raw.get("source", "")).strip(),
            license=str(raw.get("license", "")).strip(),
            license_status=license_status,
            min_vram_gib=min_vram,
            storage_gib=storage,
            priority=priority,
            enabled=enabled,
            capabilities=tuple(str(item).strip().lower() for item in raw.get("capabilities", []) if str(item).strip()),
            distributed_only=bool(raw.get("distributed_only", False)),
            min_nodes=min_nodes,
        )
        entries[key] = entry
        for alias in (model_id, *entry.aliases):
            alias_key = alias.lower()
            if alias_key in blocked or alias_key in aliases:
                raise ModelAllowlistError(f"duplicate or blocked model alias: {alias}")
            aliases[alias_key] = key

    raw_tiers = document.get("tiers")
    if not isinstance(raw_tiers, dict):
        raise ModelAllowlistError("model allowlist tiers are required")
    for tier, ids in raw_tiers.items():
        if str(tier) not in {"4", "8", "16", "32", "64", "128"}:
            raise ModelAllowlistError(f"unsupported VRAM tier: {tier}")
        if not isinstance(ids, list) or not ids:
            raise ModelAllowlistError(f"VRAM tier {tier} must contain models")
        for model_id in ids:
            if str(model_id).lower() not in aliases:
                raise ModelAllowlistError(f"tier {tier} references unknown model: {model_id}")

    return ModelAllowlist(document=dict(document), entries=entries, aliases=aliases, blocked=blocked)


@dataclass(frozen=True)
class ModelAllowlist:
    document: dict[str, Any]
    entries: dict[str, AllowedModel]
    aliases: dict[str, str]
    blocked: set[str]

    @property
    def version(self) -> str:
        return str(self.document["allowlist_version"])

    def resolve(self, model_id: str) -> AllowedModel | None:
        raw = str(model_id or "").strip().lower()
        if not raw or raw in self.blocked:
            return None
        entry_key = self.aliases.get(raw)
        entry = self.entries.get(entry_key or "")
        if entry is None or not entry.enabled:
            return None
        return entry

    def allowed_runtime_ids(self) -> set[str]:
        result: set[str] = set()
        for entry in self.entries.values():
            if entry.enabled:
                result.add(entry.model_id)
                result.update(entry.aliases)
        return result

    def filter_runtime_ids(self, model_ids: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in model_ids:
            model_id = str(raw or "").strip()
            entry = self.resolve(model_id)
            if entry is None or model_id.lower() in seen:
                continue
            result.append(model_id)
            seen.add(model_id.lower())
        return result

    def select_best(self, *, vram_gib: float, installed_ids: Iterable[str], purpose: str = "chat") -> str | None:
        installed = self.filter_runtime_ids(installed_ids)
        candidates: list[AllowedModel] = []
        for runtime_id in installed:
            entry = self.resolve(runtime_id)
            if entry is None or entry.distributed_only or entry.min_vram_gib > vram_gib:
                continue
            if purpose and purpose not in entry.capabilities and "chat" not in entry.capabilities:
                continue
            candidates.append(entry)
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item.priority, item.min_vram_gib, item.model_id), reverse=True)
        return candidates[0].model_id

    def recommendation(self, *, vram_gib: float, installed_ids: Iterable[str]) -> str | None:
        return self.select_best(vram_gib=vram_gib, installed_ids=installed_ids)


def _load_source() -> tuple[dict[str, Any], str]:
    url = os.environ.get("COMPUTEMESH_MODEL_ALLOWLIST_URL", "").strip()
    expected_sha = os.environ.get("COMPUTEMESH_MODEL_ALLOWLIST_SHA256", "").strip().lower().removeprefix("sha256:")
    if url:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ModelAllowlistError("model allowlist URL must be an HTTP(S) URL")
        if parsed.scheme != "https" and os.environ.get("COMPUTEMESH_ALLOW_INSECURE_MODEL_ALLOWLIST", "") not in {"1", "true", "TRUE"}:
            raise ModelAllowlistError("remote model allowlist must use HTTPS")
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ComputeMesh-Model-Allowlist/1"})
            with urllib.request.urlopen(request, timeout=3.0) as response:
                raw = response.read(_MAX_BYTES + 1)
            digest = hashlib.sha256(raw).hexdigest()
            if expected_sha and digest != expected_sha:
                raise ModelAllowlistError("remote model allowlist SHA-256 does not match pin")
            return _read_json_bytes(raw), digest
        except ModelAllowlistError:
            raise
        except (OSError, TimeoutError, UnicodeError, ValueError) as exc:
            if os.environ.get("COMPUTEMESH_MODEL_ALLOWLIST_ALLOW_LOCAL_FALLBACK", "") not in {"1", "true", "TRUE"}:
                raise ModelAllowlistError("authoritative remote model allowlist is unavailable") from exc
    path = Path(os.environ.get("COMPUTEMESH_MODEL_ALLOWLIST_PATH", str(_DEFAULT_PATH))).resolve()
    if path.is_symlink() or not path.is_file():
        raise ModelAllowlistError(f"model allowlist file is missing: {path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha and digest != expected_sha:
        raise ModelAllowlistError("local model allowlist SHA-256 does not match pin")
    return _read_json_bytes(raw), digest


def load_model_allowlist(*, force: bool = False) -> ModelAllowlist:
    global _CACHE
    now = time.monotonic()
    if not force and _CACHE is not None and now - _CACHE[0] < _CACHE_TTL_SECONDS:
        return _CACHE[1]
    document, _digest = _load_source()
    loaded = _validate(document)
    _CACHE = (now, loaded)
    return loaded


def reset_model_allowlist_cache() -> None:
    global _CACHE
    _CACHE = None


def detect_vram_gib() -> float:
    configured = os.environ.get("COMPUTEMESH_GPU_VRAM_GIB", "").strip()
    if configured:
        try:
            value = float(configured)
            if value > 0:
                return value
        except ValueError:
            pass
    for command in (("nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"), ("rocm-smi", "--showmeminfo", "vram")):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
            values: list[float] = []
            for line in result.stdout.splitlines():
                digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in line).split()
                if digits:
                    values.append(float(digits[-1]))
            if values:
                # nvidia-smi reports MiB; this conservative conversion is enough for tier selection.
                return max(values) / 1024.0
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return 0.0


def allowed_runtime_model(model_id: str) -> AllowedModel | None:
    return load_model_allowlist().resolve(model_id)


def filter_allowed_runtime_ids(model_ids: Iterable[str]) -> list[str]:
    return load_model_allowlist().filter_runtime_ids(model_ids)


def select_best_allowed_model(installed_ids: Iterable[str], *, vram_gib: float | None = None, purpose: str = "chat") -> str | None:
    capacity = detect_vram_gib() if vram_gib is None else float(vram_gib)
    return load_model_allowlist().select_best(vram_gib=capacity, installed_ids=installed_ids, purpose=purpose)


def model_selection_error(requested: str, *, installed_ids: Iterable[str], vram_gib: float | None = None) -> ModelAllowlistError:
    allowlist = load_model_allowlist()
    recommendation = select_best_allowed_model(installed_ids, vram_gib=vram_gib)
    visible = allowlist.filter_runtime_ids(installed_ids)
    blocked = str(requested or "").strip().lower() in allowlist.blocked
    reason = "explicitly blocked" if blocked else "not available because it is not present in the signed/authoritative allowlist"
    suffix = f" Recommended valid model: {recommendation}." if recommendation else " Install or prepare an approved model for this VRAM tier."
    error = ModelAllowlistError(f"Model '{requested}' is {reason}.{suffix}")
    error.allowed_models = visible  # type: ignore[attr-defined]
    error.recommended_model = recommendation  # type: ignore[attr-defined]
    return error


__all__ = [
    "AllowedModel",
    "ModelAllowlist",
    "ModelAllowlistError",
    "allowed_runtime_model",
    "detect_vram_gib",
    "filter_allowed_runtime_ids",
    "load_model_allowlist",
    "model_selection_error",
    "reset_model_allowlist_cache",
    "select_best_allowed_model",
]
