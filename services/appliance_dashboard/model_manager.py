"""ComputeMesh Local Model Manager & HuggingFace Hub Client.

Handles:
- Persistent model storage in /var/lib/computemesh/models
- Pre-flight disk space check (model_size * 1.15 reserve)
- Resumable chunked downloads via HTTP Range headers
- Atomic .part file downloads with SHA-256 checksum verification
- Local GGUF model inventory and Hugging Face repository search
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("computemesh.appliance.model_manager")

# Default curated high-performance GGUF models for instant provider setup
POPULAR_GGUF_MODELS = [
    {
        "id": "Qwen/Qwen2.5-32B-Instruct-GGUF",
        "name": "Qwen 2.5 32B Instruct (Q4_K_M)",
        "filename": "qwen2.5-32b-instruct-q4_k_m.gguf",
        "size_bytes": 19850000000,
        "context_length": 32768,
        "layers": 64,
        "recommended_vram_gb": 24,
        "license": "Apache 2.0",
        "url": "https://huggingface.co/Qwen/Qwen2.5-32B-Instruct-GGUF/resolve/main/qwen2.5-32b-instruct-q4_k_m.gguf",
    },
    {
        "id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "name": "Qwen 2.5 7B Instruct (Q4_K_M)",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "size_bytes": 4680000000,
        "context_length": 32768,
        "layers": 28,
        "recommended_vram_gb": 8,
        "license": "Apache 2.0",
        "url": "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf",
    },
    {
        "id": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "name": "Meta Llama 3.1 8B Instruct (Q4_K_M)",
        "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "size_bytes": 4920000000,
        "context_length": 131072,
        "layers": 32,
        "recommended_vram_gb": 8,
        "license": "Llama 3.1 Community",
        "url": "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    },
    {
        "id": "bartowski/DeepSeek-Coder-V2-Lite-Instruct-GGUF",
        "name": "DeepSeek Coder V2 Lite Instruct (Q4_K_M)",
        "filename": "DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
        "size_bytes": 9500000000,
        "context_length": 65536,
        "layers": 27,
        "recommended_vram_gb": 12,
        "license": "DeepSeek License",
        "url": "https://huggingface.co/bartowski/DeepSeek-Coder-V2-Lite-Instruct-GGUF/resolve/main/DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
    },
]


@dataclass
class DownloadProgress:
    download_id: str
    repo_id: str
    filename: str
    total_bytes: int
    downloaded_bytes: int
    speed_bytes_per_sec: float
    percent: float
    status: str  # PENDING, DOWNLOADING, VERIFYING, COMPLETED, FAILED, CANCELLED
    error_message: str | None = None
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None


@dataclass
class LocalModelInfo:
    filename: str
    path: str
    size_bytes: int
    sha256_digest: str | None
    modified_at: str
    is_active: bool = False
    context_length: int = 8192
    layers: int = 32


class ModelManager:
    """Manages local storage and Hugging Face downloads for GGUF model files."""

    _instance: ModelManager | None = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls, storage_dir: Path | None = None) -> ModelManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(storage_dir)
            return cls._instance

    def __init__(self, storage_dir: Path | None = None) -> None:
        if storage_dir is not None:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            # Check standard NodeOS path
            nodeos_path = Path("/var/lib/computemesh/models")
            if nodeos_path.exists() or os.name != "nt":
                self.storage_dir = nodeos_path
            else:
                repo_root = Path(__file__).resolve().parents[2]
                self.storage_dir = (repo_root / "data" / "models").resolve()

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.active_downloads: dict[str, DownloadProgress] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def get_storage_stats(self) -> dict[str, Any]:
        """Return total, used, and free disk space for the model storage partition."""
        try:
            total, used, free = shutil.disk_usage(self.storage_dir)
            return {
                "storage_dir": str(self.storage_dir),
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "free_gb": round(free / (1024**3), 2),
                "total_gb": round(total / (1024**3), 2),
            }
        except Exception as exc:
            log.warning(f"Error checking disk usage for {self.storage_dir}: {exc}")
            return {
                "storage_dir": str(self.storage_dir),
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0,
                "free_gb": 0.0,
                "total_gb": 0.0,
            }

    def list_local_models(self) -> list[LocalModelInfo]:
        """Scans storage directory for all available .gguf files."""
        from services.appliance_dashboard.model_engine_service import ModelEngineService
        engine = ModelEngineService.get_instance()
        active_path = engine.active_model_path

        models: list[LocalModelInfo] = []
        if not self.storage_dir.exists():
            return models

        for file in sorted(self.storage_dir.glob("*.gguf")):
            if file.is_file():
                try:
                    st = file.stat()
                    mod_time = datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat().replace("+00:00", "Z")
                    is_active = (active_path is not None and Path(active_path).resolve() == file.resolve())

                    # Heuristics for layers and context
                    fname_lower = file.name.lower()
                    layers = 32
                    ctx = 8192
                    if "32b" in fname_lower or "33b" in fname_lower:
                        layers = 64
                        ctx = 32768
                    elif "70b" in fname_lower or "72b" in fname_lower:
                        layers = 80
                        ctx = 32768
                    elif "14b" in fname_lower or "13b" in fname_lower:
                        layers = 40
                    elif "7b" in fname_lower or "8b" in fname_lower:
                        layers = 32
                    elif "3b" in fname_lower or "4b" in fname_lower:
                        layers = 24

                    models.append(
                        LocalModelInfo(
                            filename=file.name,
                            path=str(file.resolve()),
                            size_bytes=st.st_size,
                            sha256_digest=None,  # Computed on demand to avoid blocking I/O
                            modified_at=mod_time,
                            is_active=is_active,
                            context_length=ctx,
                            layers=layers,
                        )
                    )
                except Exception as exc:
                    log.warning(f"Error inspecting model file {file}: {exc}")

        return models

    def compute_sha256(self, filepath: Path, progress_callback: Any | None = None) -> str:
        """Computes SHA-256 hash in streaming 4MB blocks."""
        sha = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(4 * 1024 * 1024):
                sha.update(chunk)
                if progress_callback:
                    progress_callback(len(chunk))
        return sha.hexdigest()

    def search_huggingface(self, query: str = "") -> list[dict[str, Any]]:
        """Search Hugging Face API or return popular curated list."""
        query_clean = query.strip().lower()
        if not query_clean:
            return POPULAR_GGUF_MODELS

        # Match in popular list first
        matches = [
            m for m in POPULAR_GGUF_MODELS
            if query_clean in m["id"].lower() or query_clean in m["name"].lower() or query_clean in m["filename"].lower()
        ]
        if matches:
            return matches

        # Query Hugging Face Hub API
        try:
            encoded_q = urllib.parse.quote(f"{query} gguf")
            url = f"https://huggingface.co/api/models?search={encoded_q}&limit=10&full=true"
            req = urllib.request.Request(url, headers={"User-Agent": "ComputeMesh-NodeOS/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results: list[dict[str, Any]] = []
                for item in data:
                    repo_id = item.get("id", "")
                    results.append({
                        "id": repo_id,
                        "name": repo_id.split("/")[-1],
                        "filename": f"{repo_id.split('/')[-1]}.gguf",
                        "size_bytes": 0,
                        "context_length": 8192,
                        "layers": 32,
                        "recommended_vram_gb": 16,
                        "license": item.get("cardData", {}).get("license", "unknown"),
                        "url": f"https://huggingface.co/{repo_id}",
                    })
                return results
        except Exception as exc:
            log.warning(f"HuggingFace search error: {exc}")
            return [m for m in POPULAR_GGUF_MODELS if query_clean in m["id"].lower() or query_clean in m["name"].lower()]

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitizes filename and validates that it remains strictly inside storage_dir."""
        clean_name = os.path.basename(filename).strip()
        if not clean_name or clean_name != filename:
            raise ValueError(f"Invalid model filename: {filename}")
        if not clean_name.lower().endswith(".gguf"):
            raise ValueError("Only .gguf model files are permitted.")
        if ".." in clean_name or "/" in clean_name or "\\" in clean_name:
            raise ValueError(f"Directory traversal prohibited: {filename}")
        for char in clean_name:
            if not (char.isalnum() or char in ("-", "_", ".")):
                raise ValueError(f"Disallowed character in filename: {char}")

        target_path = (self.storage_dir / clean_name).resolve()
        storage_root = self.storage_dir.resolve()
        try:
            target_path.relative_to(storage_root)
        except ValueError as exc:
            raise ValueError(f"Path traversal outside storage directory: {target_path}") from exc

        return clean_name

    def _validate_download_url(self, url: str) -> str:
        """Validates that download URL uses secure HTTPS or local test endpoint."""
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme == "https":
            return url.strip()
        if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
            return url.strip()
        raise ValueError(f"Insecure or invalid download URL: {url}. Must use https:// or loopback test URL.")

    def _verify_gguf_magic(self, filepath: Path) -> bool:
        """Verifies GGUF binary magic bytes (0x46554747 = 'GGUF') at file start."""
        try:
            if not filepath.exists() or filepath.stat().st_size < 4:
                return False
            with open(filepath, "rb") as f:
                magic = f.read(4)
                return magic == b"GGUF"
        except Exception as exc:
            log.warning(f"Error checking GGUF magic header for {filepath}: {exc}")
            return False

    def fetch_huggingface_metadata(self, repo_id: str, filename: str) -> dict[str, Any] | None:
        """Fetches file SHA-256 and size from Hugging Face Model API."""
        clean_repo = repo_id.strip()
        clean_file = self._sanitize_filename(filename)
        if not clean_repo:
            return None
        try:
            url = f"https://huggingface.co/api/models/{clean_repo}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "ComputeMesh-NodeOS/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    siblings = data.get("siblings", [])
                    for s in siblings:
                        if s.get("rfilename") == clean_file:
                            lfs = s.get("lfs", {})
                            return {
                                "filename": clean_file,
                                "sha256": lfs.get("oid") or lfs.get("sha256"),
                                "size_bytes": lfs.get("size", 0),
                            }
        except Exception as exc:
            log.debug(f"Could not fetch HF metadata for {clean_repo}/{clean_file}: {exc}")
        return None

    def start_download(
        self,
        url: str,
        filename: str,
        repo_id: str = "",
        expected_size_bytes: int = 0,
        expected_sha256: str | None = None,
    ) -> str:
        """Starts a background resumable atomic download with strict path & URL verification."""
        clean_name = self._sanitize_filename(filename)
        valid_url = self._validate_download_url(url)

        # Auto-fetch expected sha256 & size from HF if repo_id provided and sha not given
        if repo_id and not expected_sha256:
            meta = self.fetch_huggingface_metadata(repo_id, clean_name)
            if meta:
                if meta.get("sha256"):
                    expected_sha256 = meta["sha256"]
                if meta.get("size_bytes") and expected_size_bytes == 0:
                    expected_size_bytes = meta["size_bytes"]

        download_id = f"dl_{int(time.time())}_{clean_name}"
        with self._lock:
            # Pre-flight disk space check: require 15% safety reserve
            stats = self.get_storage_stats()
            required_space = int(expected_size_bytes * 1.15) if expected_size_bytes > 0 else (1024**3)
            if stats["free_bytes"] > 0 and stats["free_bytes"] < required_space:
                raise ValueError(
                    f"Insufficient disk space. Free: {stats['free_gb']} GB, Required: {round(required_space / (1024**3), 2)} GB"
                )

            prog = DownloadProgress(
                download_id=download_id,
                repo_id=repo_id or valid_url,
                filename=clean_name,
                total_bytes=expected_size_bytes,
                downloaded_bytes=0,
                speed_bytes_per_sec=0.0,
                percent=0.0,
                status="PENDING",
            )
            self.active_downloads[download_id] = prog
            cancel_event = threading.Event()
            self._cancel_flags[download_id] = cancel_event

        # Spawn download thread
        th = threading.Thread(
            target=self._download_worker,
            args=(download_id, valid_url, clean_name, expected_size_bytes, expected_sha256, cancel_event),
            daemon=True,
        )
        th.start()
        return download_id

    def cancel_download(self, download_id: str) -> bool:
        """Signals cancellation for an active download."""
        with self._lock:
            if download_id in self._cancel_flags:
                self._cancel_flags[download_id].set()
                if download_id in self.active_downloads:
                    self.active_downloads[download_id].status = "CANCELLED"
                return True
        return False

    def delete_model(self, filename: str) -> bool:
        """Deletes a local model file if not currently loaded with strict path traversal containment."""
        clean_name = self._sanitize_filename(filename)
        from services.appliance_dashboard.model_engine_service import ModelEngineService
        engine = ModelEngineService.get_instance()
        target_path = (self.storage_dir / clean_name).resolve()

        if engine.active_model_path and Path(engine.active_model_path).resolve() == target_path:
            raise ValueError(f"Cannot delete actively loaded model '{clean_name}'. Deactivate it first.")

        if target_path.exists() and target_path.is_file():
            target_path.unlink()
            log.info(f"Model file {clean_name} deleted.")
            return True
        return False

    def _download_worker(
        self,
        download_id: str,
        url: str,
        filename: str,
        expected_size: int,
        expected_sha256: str | None,
        cancel_event: threading.Event,
    ) -> None:
        clean_name = self._sanitize_filename(filename)
        target_file = (self.storage_dir / clean_name).resolve()
        part_file = (self.storage_dir / f"{clean_name}.part").resolve()

        prog = self.active_downloads[download_id]
        prog.status = "DOWNLOADING"

        existing_bytes = 0
        if part_file.exists():
            existing_bytes = part_file.stat().st_size
            prog.downloaded_bytes = existing_bytes

        headers: dict[str, str] = {
            "User-Agent": "ComputeMesh-NodeOS/1.0",
        }
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"
            log.info(f"Resuming download of {clean_name} from byte {existing_bytes}")

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = getattr(resp, "status", 200)
                total_len = resp.headers.get("Content-Length")
                if total_len:
                    if status_code == 206:  # Partial Content
                        prog.total_bytes = existing_bytes + int(total_len)
                    else:
                        prog.total_bytes = int(total_len)
                        existing_bytes = 0

                mode = "ab" if (existing_bytes > 0 and status_code == 206) else "wb"
                bytes_downloaded = existing_bytes
                last_time = time.time()
                bytes_since_last = 0

                with open(part_file, mode) as f:
                    while not cancel_event.is_set():
                        chunk = resp.read(1024 * 1024)  # 1MB buffer
                        if not chunk:
                            break
                        f.write(chunk)
                        chunk_len = len(chunk)
                        bytes_downloaded += chunk_len
                        bytes_since_last += chunk_len
                        prog.downloaded_bytes = bytes_downloaded

                        if prog.total_bytes > 0:
                            prog.percent = round((bytes_downloaded / prog.total_bytes) * 100.0, 2)

                        now = time.time()
                        elapsed = now - last_time
                        if elapsed >= 1.0:
                            prog.speed_bytes_per_sec = bytes_since_last / elapsed
                            bytes_since_last = 0
                            last_time = now

                if cancel_event.is_set():
                    log.info(f"Download {download_id} cancelled by user.")
                    prog.status = "CANCELLED"
                    return

            # Verification phase
            prog.status = "VERIFYING"
            prog.percent = 100.0

            # 1. Verify GGUF magic bytes
            if not self._verify_gguf_magic(part_file):
                prog.status = "FAILED"
                prog.error_message = f"Downloaded file {clean_name} is not a valid GGUF binary (invalid magic header)."
                log.error(prog.error_message)
                if part_file.exists():
                    part_file.unlink()
                return

            # 2. Verify SHA-256 Checksum
            if expected_sha256:
                log.info(f"Verifying SHA-256 for {part_file.name}...")
                actual_sha = self.compute_sha256(part_file)
                if actual_sha.lower() != expected_sha256.lower().replace("sha256:", ""):
                    prog.status = "FAILED"
                    prog.error_message = f"Checksum mismatch: expected {expected_sha256}, got {actual_sha}"
                    log.error(prog.error_message)
                    if part_file.exists():
                        part_file.unlink()
                    return

            # Atomic rename
            if target_file.exists():
                target_file.unlink()
            part_file.rename(target_file)

            prog.status = "COMPLETED"
            prog.completed_at = time.time()
            log.info(f"Download completed successfully: {target_file}")

        except Exception as exc:
            log.error(f"Download failed for {url}: {exc}")
            prog.status = "FAILED"
            prog.error_message = str(exc)
