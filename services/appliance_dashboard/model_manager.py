"""Verified local GGUF catalogue and Hugging Face download management."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any
import urllib.parse
import urllib.request

from services.appliance_dashboard.model_engine_service import (
    EngineModel,
    ModelEngineError,
    ModelEngineService,
    get_model_engine_service,
)


MAX_MODEL_BYTES = 1024 * 1024 * 1024 * 1024
MAX_SEARCH_RESULTS = 25
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
        with self._lock:
            return {
                "model_root": str(self.model_root),
                "storage": {"total_bytes": usage.total, "free_bytes": usage.free},
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
        if free_bytes < int(size_bytes) + 1024 * 1024 * 1024:
            raise ModelManagerError("insufficient free storage for the model and safety reserve")
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

    def activate(self, model_id: str, *, context_size: int = 4096) -> dict[str, Any]:
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
