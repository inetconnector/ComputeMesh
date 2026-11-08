"""Verified local GGUF catalogue and Hugging Face download management."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from services.appliance_dashboard.model_engine_service import (
    EngineModel,
    ModelEngineError,
    ModelEngineService,
    get_model_engine_service,
)

MAX_MODEL_BYTES = 1024 * 1024 * 1024 * 1024
MAX_SEARCH_RESULTS = 25
MODEL_SAFETY_RESERVE_BYTES = 1024 * 1024 * 1024
# A node with less space than this cannot practically host the standard local
# GGUF catalogue. Smaller models remain possible when their manifest fits.
RECOMMENDED_MIN_MODEL_BYTES = 3 * 1024 * 1024 * 1024
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


class ModelManagerError(RuntimeError):
    """Raised when model state or artifact input is invalid."""


@dataclass(frozen=True)
class InstalledModel:
    model_id: str
    filename: str
    sha256: str
    size_bytes: int
    layer_count: int
    quantization: str
    license_id: str
    source_repo: str
    source_revision: str
    installed_at: str


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _mount_diagnostics(path: Path) -> dict[str, Any]:
    """Return the Linux mount carrying *path* without shelling out to findmnt."""
    if os.name == "nt":
        return {}
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return {}
    target = str(path.resolve())
    best: tuple[int, dict[str, Any]] | None = None
    try:
        for line in mountinfo.read_text(encoding="utf-8").splitlines():
            before, separator, after = line.partition(" - ")
            if not separator:
                continue
            fields = before.split()
            if len(fields) < 6:
                continue
            mount_point = fields[4].replace("\\040", " ").replace("\\011", "\t")
            if target != mount_point and not target.startswith(mount_point.rstrip("/") + "/"):
                continue
            after_fields = after.split()
            if not after_fields:
                continue
            details = {
                "mount_point": mount_point,
                "filesystem_type": after_fields[0],
                "mount_source": after_fields[1] if len(after_fields) > 1 else "",
            }
            candidate = (len(mount_point), details)
            if best is None or candidate[0] > best[0]:
                best = candidate
    except (OSError, UnicodeError):
        return {}
    return best[1] if best else {}


class ModelManager:
    """Persist verified model metadata and coordinate the local engine."""

    def __init__(self, model_root: Path, engine: ModelEngineService | None = None) -> None:
        self.model_root = model_root.resolve()
        self.model_root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.model_root / "catalog.json"
        self.engine = engine or get_model_engine_service(model_root=self.model_root)
        self._lock = threading.RLock()
        self._downloads: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _validate_identity(model_id: str, repo_id: str, filename: str, revision: str) -> None:
        if not MODEL_ID_RE.fullmatch(model_id):
            raise ModelManagerError("invalid model_id")
        if not MODEL_ID_RE.fullmatch(repo_id) or repo_id.count("/") != 1:
            raise ModelManagerError("invalid Hugging Face repo_id")
        if Path(filename).name != filename or not filename.lower().endswith(".gguf"):
            raise ModelManagerError("filename must be one local GGUF basename")
        if not REVISION_RE.fullmatch(revision):
            raise ModelManagerError("source_revision must be a full 40-character commit SHA")

    def _load(self) -> dict[str, InstalledModel]:
        if not self.index_path.exists():
            return {}
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("models"), list):
                raise ValueError
            result: dict[str, InstalledModel] = {}
            for item in raw["models"]:
                model = InstalledModel(**item)
                result[model.model_id] = model
            return result
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ModelManagerError("local model catalogue is corrupt") from exc

    def _save(self, models: dict[str, InstalledModel]) -> None:
        _atomic_json(
            self.index_path,
            {"schema_version": 1, "models": [asdict(models[key]) for key in sorted(models)]},
        )

    def list_models(self) -> list[dict[str, Any]]:
        with self._lock:
            models = self._load()
            engine_status = self.engine.status()
            result = []
            for model in models.values():
                artifact = self.model_root / model.filename
                present = artifact.is_file() and not artifact.is_symlink() and artifact.stat().st_size == model.size_bytes
                result.append({
                    **asdict(model),
                    "present": present,
                    "active": bool(engine_status["ready"] and engine_status["model_id"] == model.model_id),
                })
            return sorted(result, key=lambda item: item["model_id"])

    def status(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.model_root)
        recommended_required = RECOMMENDED_MIN_MODEL_BYTES + MODEL_SAFETY_RESERVE_BYTES
        mount = _mount_diagnostics(self.model_root)
        warning = usage.free < recommended_required
        overlay = mount.get("filesystem_type") == "overlay"
        with self._lock:
            return {
                "model_root": str(self.model_root),
                "storage": {
                    "total_bytes": usage.total,
                    "free_bytes": usage.free,
                    "safety_reserve_bytes": MODEL_SAFETY_RESERVE_BYTES,
                    "recommended_minimum_model_bytes": RECOMMENDED_MIN_MODEL_BYTES,
                    "recommended_required_bytes": recommended_required,
                    "sufficient_for_recommended_model": usage.free >= recommended_required,
                    "warning": warning or overlay,
                    "warning_reason": "overlay" if overlay else ("low_space" if warning else ""),
                    "persistence_volume_detected": not overlay if mount else None,
                    **mount,
                },
                "models": self.list_models(),
                "downloads": list(self._downloads.values()),
                "engine": self.engine.status(),
            }

    def search_hugging_face(self, query: str) -> list[dict[str, Any]]:
        query = query.strip()
        if not 2 <= len(query) <= 128:
            raise ModelManagerError("search query must contain 2..128 characters")
        url = "https://huggingface.co/api/models?" + urllib.parse.urlencode({
            "search": query,
            "filter": "gguf",
            "limit": MAX_SEARCH_RESULTS,
            "full": "false",
        })
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ComputeMesh-NodeOS/1"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except Exception as exc:
            raise ModelManagerError("Hugging Face search is unavailable") from exc
        if len(raw) > 2 * 1024 * 1024:
            raise ModelManagerError("Hugging Face search response exceeded the size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ModelManagerError("Hugging Face returned an invalid search response") from exc
        if not isinstance(payload, list):
            raise ModelManagerError("Hugging Face returned an invalid search response")
        return [
            {
                "repo_id": str(item.get("id", "")),
                "downloads": int(item.get("downloads", 0) or 0),
                "likes": int(item.get("likes", 0) or 0),
                "private": bool(item.get("private", False)),
            }
            for item in payload[:MAX_SEARCH_RESULTS]
            if isinstance(item, dict) and MODEL_ID_RE.fullmatch(str(item.get("id", "")))
        ]

    def install_from_hugging_face(
        self,
        *,
        model_id: str,
        repo_id: str,
        filename: str,
        revision: str,
        sha256: str,
        size_bytes: int,
        layer_count: int,
        quantization: str,
        license_id: str,
        _allow_queued: bool = False,
    ) -> dict[str, Any]:
        self._validate_identity(model_id, repo_id, filename, revision)
        match = SHA256_RE.fullmatch(str(sha256).lower())
        if not match:
            raise ModelManagerError("sha256 must be a lowercase SHA-256 digest")
        expected_sha = match.group(1)
        if not 1 <= int(size_bytes) <= MAX_MODEL_BYTES:
            raise ModelManagerError("size_bytes is outside the supported range")
        if not 2 <= int(layer_count) <= 100_000:
            raise ModelManagerError("layer_count is outside the supported range")
        if not quantization or len(quantization) > 64 or not license_id or len(license_id) > 256:
            raise ModelManagerError("quantization and license_id are required")

        free_bytes = shutil.disk_usage(self.model_root).free
        required_bytes = int(size_bytes) + MODEL_SAFETY_RESERVE_BYTES
        if free_bytes < required_bytes:
            raise ModelManagerError(
                "insufficient free storage: "
                f"{free_bytes} bytes available, {required_bytes} bytes required "
                f"(model plus {MODEL_SAFETY_RESERVE_BYTES} byte safety reserve)"
            )
        target = self.model_root / filename
        partial = target.with_suffix(target.suffix + ".part")
        download_id = hashlib.sha256(f"{repo_id}\0{revision}\0{filename}".encode()).hexdigest()[:24]
        with self._lock:
            if model_id in self._load():
                raise ModelManagerError("model_id is already installed")
            existing_state = self._downloads.get(download_id, {})
            if existing_state.get("state") == "downloading":
                raise ModelManagerError("model download is already running")
            if existing_state.get("state") == "queued" and not _allow_queued:
                raise ModelManagerError("model download is already queued")
        if target.exists():
            raise ModelManagerError("model artifact already exists outside the catalogue")
        existing_bytes = partial.stat().st_size if partial.exists() else 0
        if existing_bytes > int(size_bytes):
            partial.unlink(missing_ok=True)
            raise ModelManagerError("partial download exceeds the declared artifact size")

        quoted_repo = "/".join(urllib.parse.quote(part, safe="") for part in repo_id.split("/"))
        url = f"https://huggingface.co/{quoted_repo}/resolve/{revision}/{urllib.parse.quote(filename, safe='')}"
        state = {
            "download_id": download_id,
            "model_id": model_id,
            "state": "downloading",
            "bytes_total": int(size_bytes),
            "bytes_downloaded": existing_bytes,
            "error": "",
        }
        with self._lock:
            self._downloads[download_id] = state

        headers = {"Accept": "application/octet-stream", "User-Agent": "ComputeMesh-NodeOS/1"}
        if existing_bytes:
            headers["Range"] = f"bytes={existing_bytes}-"
        request = urllib.request.Request(url, headers=headers)
        discard_partial = False
        try:
            digest = hashlib.sha256()
            if existing_bytes:
                with partial.open("rb") as existing:
                    for chunk in iter(lambda: existing.read(8 * 1024 * 1024), b""):
                        digest.update(chunk)
            with urllib.request.urlopen(request, timeout=60) as response, partial.open("ab" if existing_bytes else "xb") as output:
                if existing_bytes and getattr(response, "status", response.getcode()) != 206:
                    raise ModelManagerError("remote server did not honor the resume range")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) != int(size_bytes) - existing_bytes:
                    raise ModelManagerError("remote Content-Length does not match the declared artifact size")
                written = existing_bytes
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > int(size_bytes):
                        discard_partial = True
                        raise ModelManagerError("download exceeded its declared size")
                    output.write(chunk)
                    digest.update(chunk)
                    state["bytes_downloaded"] = written
                if written != int(size_bytes):
                    raise ModelManagerError("download size does not match the declared artifact size")
                if digest.hexdigest() != expected_sha:
                    discard_partial = True
                    raise ModelManagerError("download SHA-256 does not match the declared digest")
                output.flush()
                os.fsync(output.fileno())
            with partial.open("rb") as handle:
                if handle.read(4) != b"GGUF":
                    discard_partial = True
                    raise ModelManagerError("downloaded artifact is not a GGUF file")
            os.replace(partial, target)
            model = InstalledModel(
                model_id=model_id,
                filename=filename,
                sha256=expected_sha,
                size_bytes=int(size_bytes),
                layer_count=int(layer_count),
                quantization=quantization,
                license_id=license_id,
                source_repo=repo_id,
                source_revision=revision,
                installed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            with self._lock:
                models = self._load()
                if model_id in models:
                    raise ModelManagerError("model_id is already installed")
                models[model_id] = model
                self._save(models)
            state["state"] = "complete"
            return {**asdict(model), "download_id": download_id}
        except Exception as exc:
            if discard_partial:
                partial.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            state["state"] = "failed"
            state["error"] = str(exc)
            if isinstance(exc, ModelManagerError):
                raise
            raise ModelManagerError("model download failed") from exc

    def start_download(self, **kwargs: Any) -> dict[str, Any]:
        """Queue a verified download without blocking the dashboard request thread."""
        model_id = str(kwargs.get("model_id", ""))
        repo_id = str(kwargs.get("repo_id", ""))
        filename = str(kwargs.get("filename", ""))
        revision = str(kwargs.get("revision", ""))
        self._validate_identity(model_id, repo_id, filename, revision)
        download_id = hashlib.sha256(f"{repo_id}\0{revision}\0{filename}".encode()).hexdigest()[:24]
        with self._lock:
            prior = self._downloads.get(download_id, {})
            if prior.get("state") in {"queued", "downloading"}:
                raise ModelManagerError("model download is already queued or running")
            self._downloads[download_id] = {
                "download_id": download_id,
                "model_id": model_id,
                "state": "queued",
                "bytes_total": int(kwargs.get("size_bytes", 0)),
                "bytes_downloaded": 0,
                "error": "",
            }

        def worker() -> None:
            try:
                self.install_from_hugging_face(**kwargs, _allow_queued=True)
            except ModelManagerError:
                pass

        threading.Thread(target=worker, name=f"model-download-{download_id}", daemon=True).start()
        return {"accepted": True, "download_id": download_id, "model_id": model_id, "state": "queued"}

    def activate(self, model_id: str, *, context_size: int = 8192) -> dict[str, Any]:
        with self._lock:
            model = self._load().get(model_id)
        if model is None:
            raise ModelManagerError("model is not installed")
        try:
            return self.engine.start(
                EngineModel(model.model_id, self.model_root / model.filename, model.sha256, model.size_bytes, model.layer_count),
                context_size=context_size,
            )
        except ModelEngineError as exc:
            raise ModelManagerError(str(exc)) from exc

    def deactivate(self, model_id: str) -> dict[str, Any]:
        status = self.engine.status()
        if status["model_id"] and status["model_id"] != model_id:
            raise ModelManagerError("requested model is not the active model")
        return self.engine.stop()

    def delete(self, model_id: str) -> dict[str, Any]:
        if self.engine.status()["model_id"] == model_id:
            raise ModelManagerError("active model must be stopped before deletion")
        with self._lock:
            models = self._load()
            model = models.pop(model_id, None)
            if model is None:
                raise ModelManagerError("model is not installed")
            artifact = (self.model_root / model.filename).resolve()
            try:
                artifact.relative_to(self.model_root)
            except ValueError as exc:
                raise ModelManagerError("registered model path escapes the model root") from exc
            artifact.unlink(missing_ok=True)
            self._save(models)
        return {"deleted": True, "model_id": model_id}

    def discover_and_register_local_artifacts(self) -> list[str]:
        """Scan model_root for valid GGUF files and register any missing into catalog.json."""
        with self._lock:
            models = self._load()
            registered_filenames = {m.filename for m in models.values()}
            registered_ids = set(models.keys())
            discovered: list[str] = []

            for gguf_file in sorted(self.model_root.glob("*.gguf")):
                if gguf_file.is_symlink() or not gguf_file.is_file():
                    continue
                if gguf_file.name in registered_filenames:
                    continue

                size = gguf_file.stat().st_size
                if size < 1024 * 1024:
                    continue

                manifest_data: dict[str, Any] = {}
                candidate_manifests = [
                    gguf_file.with_suffix(".computemesh-model-manifest.json"),
                    gguf_file.with_suffix(".json"),
                    self.model_root / f"{gguf_file.stem}.computemesh-model-manifest.json",
                ]
                for cm in candidate_manifests:
                    if cm.is_file():
                        try:
                            manifest_data = json.loads(cm.read_text(encoding="utf-8"))
                            break
                        except Exception:
                            pass

                model_id = str(manifest_data.get("model_id") or gguf_file.stem).lower()
                model_id = re.sub(r"[^A-Za-z0-9._/-]", "-", model_id).strip("-")
                if not model_id:
                    model_id = f"local-model-{len(models) + 1}"

                if model_id in registered_ids:
                    model_id = f"{model_id}-{len(models) + 1}"

                digest = ""
                art_list = manifest_data.get("artifacts", [])
                if art_list and isinstance(art_list[0], dict) and art_list[0].get("digest"):
                    raw_d = str(art_list[0]["digest"]).removeprefix("sha256:")
                    if len(raw_d) == 64:
                        digest = raw_d
                if not digest:
                    h = hashlib.sha256()
                    with gguf_file.open("rb") as f:
                        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                            h.update(chunk)
                    digest = h.hexdigest()

                layer_count = int(manifest_data.get("layer_count", 0) or 0)
                if layer_count <= 0:
                    if size > 16 * 1024 * 1024 * 1024:
                        layer_count = 64
                    elif size > 8 * 1024 * 1024 * 1024:
                        layer_count = 48
                    elif size > 3 * 1024 * 1024 * 1024:
                        layer_count = 32
                    else:
                        layer_count = 24

                quant = ""
                quants = manifest_data.get("quantizations", [])
                if quants and isinstance(quants, list):
                    quant = str(quants[0])
                if not quant:
                    m = re.search(r"(Q[0-9]_[A-Za-z0-9_]+|BF16|F16|F32)", gguf_file.name, re.IGNORECASE)
                    quant = m.group(1).upper() if m else "Q4_K_M"

                license_id = str(manifest_data.get("license", {}).get("id", "apache-2.0") or "apache-2.0")
                source_repo = str(manifest_data.get("upstream", {}).get("model_name", f"local/{model_id}") or f"local/{model_id}")
                if "/" not in source_repo:
                    source_repo = f"local/{source_repo}"
                source_revision = "0" * 40

                inst_model = InstalledModel(
                    model_id=model_id,
                    filename=gguf_file.name,
                    sha256=digest,
                    size_bytes=size,
                    layer_count=layer_count,
                    quantization=quant,
                    license_id=license_id,
                    source_repo=source_repo,
                    source_revision=source_revision,
                    installed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
                models[model_id] = inst_model
                registered_filenames.add(gguf_file.name)
                registered_ids.add(model_id)
                discovered.append(model_id)

            if discovered:
                self._save(models)
            return discovered

    def ensure_best_model_for_rig(self, inventory: Any | None = None) -> dict[str, Any] | None:
        """Automatically selects, discovers, and activates the optimal model matching the node's VRAM tier."""
        self.discover_and_register_local_artifacts()

        total_vram_bytes = 0
        if inventory is not None:
            gpus = getattr(inventory, "gpus", None)
            if gpus is None and isinstance(inventory, dict):
                gpus = inventory.get("gpus", [])
            if gpus:
                try:
                    from tools.appliance.hardware_detector import is_integrated_display_adapter
                    for g in gpus:
                        if isinstance(g, dict):
                            vendor = g.get("vendor", "")
                            model_name = g.get("model_name", "")
                            vram = int(g.get("vram_bytes", 0) or 0)
                            healthy = bool(g.get("healthy", True))
                            if healthy and not is_integrated_display_adapter(vendor, model_name):
                                total_vram_bytes += vram
                        elif hasattr(g, "vram_bytes"):
                            vendor = getattr(g, "vendor", "")
                            model_name = getattr(g, "model_name", "")
                            vram = int(getattr(g, "vram_bytes", 0) or 0)
                            healthy = bool(getattr(g, "healthy", True))
                            if healthy and not is_integrated_display_adapter(vendor, model_name):
                                total_vram_bytes += vram
                except Exception:
                    pass

        if total_vram_bytes == 0:
            try:
                from tools.appliance.hardware_detector import is_integrated_display_adapter, scan_rig_hardware_stable
                detected = scan_rig_hardware_stable()
                for g in detected.gpus:
                    if g.healthy and not is_integrated_display_adapter(g.vendor, g.model_name):
                        total_vram_bytes += g.vram_bytes
            except Exception:
                pass

        total_vram_gb = total_vram_bytes / (1024**3)

        if total_vram_gb >= 36.0:
            tier_preferences = ["32b", "30b", "27b", "14b", "8b", "7b", "3b", "1.5b", "0.5b"]
            tier_target = "bartowski/qwen2.5-32b-instruct-gguf"
            tier_name = "48GB_TIER"
        elif total_vram_gb >= 12.0:
            tier_preferences = ["14b", "8b", "7b", "3b", "1.5b", "0.5b"]
            tier_target = "bartowski/qwen2.5-14b-instruct-gguf"
            tier_name = "16GB_TIER"
        else:
            tier_preferences = ["3b", "1.5b", "0.5b"]
            tier_target = "bartowski/qwen2.5-7b-instruct-gguf"
            tier_name = "8GB_TIER"

        with self._lock:
            models = self._load()
            if not models:
                return None

            candidates = []
            for m in models.values():
                artifact = self.model_root / m.filename
                if artifact.is_file() and not artifact.is_symlink() and artifact.stat().st_size == m.size_bytes:
                    candidates.append(m)

            if not candidates:
                return None

            def score_model(m: InstalledModel) -> int:
                name = (m.model_id + " " + m.filename).lower()
                for rank, token in enumerate(tier_preferences):
                    if token in name:
                        coder_bonus = 10 if "coder" in name else 0
                        return 1000 - (rank * 20) + coder_bonus
                return 0

            candidates.sort(key=score_model, reverse=True)
            best_model = candidates[0]

            engine_status = self.engine.status()
            if engine_status.get("ready") and engine_status.get("model_id") == best_model.model_id:
                return {
                    "model_id": best_model.model_id,
                    "status": "already_active",
                    "total_vram_gb": round(total_vram_gb, 1),
                    "target_model_id": tier_target,
                    "tier": tier_name,
                    "tier_target_active": bool(best_model.model_id == tier_target or tier_preferences[0] in (best_model.model_id + " " + best_model.filename).lower()),
                }

        result = self.activate(best_model.model_id)
        return {
            "model_id": best_model.model_id,
            "status": "activated",
            "total_vram_gb": round(total_vram_gb, 1),
            "target_model_id": tier_target,
            "tier": tier_name,
            "tier_target_active": bool(best_model.model_id == tier_target or tier_preferences[0] in (best_model.model_id + " " + best_model.filename).lower()),
            "engine": result,
        }


_MANAGER: ModelManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_model_manager() -> ModelManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            configured = os.environ.get("COMPUTEMESH_MODEL_DIR", "").strip()
            root = Path(configured) if configured else (
                Path.home() / ".computemesh" / "models" if os.name == "nt" else Path("/var/lib/computemesh/models")
            )
            _MANAGER = ModelManager(root)
        return _MANAGER
