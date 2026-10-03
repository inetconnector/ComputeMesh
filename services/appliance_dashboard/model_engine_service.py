"""Supervise one verified local llama-server instance for a provider node."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any, Callable
import urllib.request

from tools.appliance.hardware_detector import RigInventory
from tools.appliance.multi_gpu_launcher import (
    MultiGpuPlan,
    build_llama_server_command,
    compute_multi_gpu_allocation,
)


class ModelEngineError(RuntimeError):
    """Raised when a model cannot be started or stopped safely."""


@dataclass(frozen=True)
class EngineModel:
    model_id: str
    path: Path
    sha256: str
    size_bytes: int
    layer_count: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelEngineService:
    """Own the lifecycle and readiness state of one local llama-server."""

    def __init__(
        self,
        *,
        model_root: Path,
        inventory_provider: Callable[[], RigInventory],
        executable: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8081,
        startup_timeout_seconds: float = 90.0,
        process_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    ) -> None:
        self.model_root = model_root.resolve()
        self.inventory_provider = inventory_provider
        self.executable = executable or os.environ.get("COMPUTEMESH_LLAMA_SERVER", "llama-server")
        self.host = host
        self.port = int(port)
        self.startup_timeout_seconds = float(startup_timeout_seconds)
        self._process_factory = process_factory
        self._lock = threading.RLock()
        self._process: subprocess.Popen[Any] | None = None
        self._model: EngineModel | None = None
        self._plan: MultiGpuPlan | None = None
        self._started_at = 0.0
        self._last_error = ""

    def _resolve_model(self, model: EngineModel) -> EngineModel:
        try:
            path = model.path.resolve(strict=True)
            path.relative_to(self.model_root)
        except (OSError, ValueError) as exc:
            raise ModelEngineError("model artifact must be a regular file beneath the model root") from exc
        if path.is_symlink() or not path.is_file():
            raise ModelEngineError("model artifact must be a regular non-symlink file")
        if path.stat().st_size != model.size_bytes or model.size_bytes <= 0:
            raise ModelEngineError("model artifact size does not match its registered metadata")
        with path.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                raise ModelEngineError("model artifact is not a GGUF file")
        if _sha256_file(path) != model.sha256.lower().removeprefix("sha256:"):
            raise ModelEngineError("model artifact SHA-256 does not match its registered metadata")
        if model.layer_count < 2:
            raise ModelEngineError("model layer count is invalid")
        return EngineModel(model.model_id, path, model.sha256.lower().removeprefix("sha256:"), model.size_bytes, model.layer_count)

    def _binary(self) -> str:
        candidate = Path(self.executable)
        if candidate.is_absolute():
            if not candidate.is_file():
                raise ModelEngineError(f"llama-server executable not found: {candidate}")
            return str(candidate)
        resolved = shutil.which(self.executable)
        if not resolved:
            raise ModelEngineError("llama-server executable is not installed")
        return resolved

    def _health(self, timeout: float = 1.5) -> bool:
        try:
            request = urllib.request.Request(
                f"http://{self.host}:{self.port}/health",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status == 200
        except Exception:
            return False

    def start(self, model: EngineModel, *, context_size: int = 4096) -> dict[str, Any]:
        verified = self._resolve_model(model)
        if not 128 <= int(context_size) <= 131_072:
            raise ModelEngineError("context_size must be between 128 and 131072")
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                if self._model and self._model.model_id == verified.model_id and self._health():
                    return self.status()
                raise ModelEngineError("another model is already active; stop it before starting a new model")

            inventory = self.inventory_provider()
            plan = compute_multi_gpu_allocation(inventory, total_model_layers=verified.layer_count)
            reserve_bytes = max(0, int(os.environ.get("COMPUTEMESH_MODEL_VRAM_RESERVE_MB", "512"))) * 1024 * 1024
            usable_vram = max(0, plan.total_vram_bytes - reserve_bytes * plan.total_gpus)
            if verified.size_bytes > usable_vram:
                raise ModelEngineError("model weights exceed the configured aggregate VRAM budget")

            command = build_llama_server_command(
                self._binary(),
                str(verified.path),
                plan,
                host=self.host,
                port=self.port,
                context_size=int(context_size),
                extra_args=("--alias", verified.model_id, "--parallel", "1"),
                device_names=os.environ.get("COMPUTEMESH_LLAMA_DEVICE_NAMES", "").strip() or None,
            )
            log_path = self.model_root / "llama-server.log"
            log_handle = log_path.open("ab", buffering=0)
            try:
                process = self._process_factory(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    cwd=str(self.model_root),
                )
            except Exception:
                log_handle.close()
                raise
            log_handle.close()

            self._process = process
            self._model = verified
            self._plan = plan
            self._started_at = time.time()
            self._last_error = ""

        deadline = time.monotonic() + self.startup_timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._last_error = f"llama-server exited during startup with code {process.returncode}"
                self.stop()
                raise ModelEngineError(self._last_error)
            if self._health():
                return self.status()
            time.sleep(0.25)
        self._last_error = "llama-server did not become healthy before the startup timeout"
        self.stop()
        raise ModelEngineError(self._last_error)

    def stop(self, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=max(0.1, timeout_seconds))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self._process = None
            self._model = None
            self._plan = None
            self._started_at = 0.0
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
            healthy = running and self._health(timeout=0.5)
            model = self._model
            plan = self._plan
            return {
                "state": "ready" if healthy else ("starting" if running else "stopped"),
                "ready": bool(healthy),
                "model_id": model.model_id if model else "",
                "model_sha256": model.sha256 if model else "",
                "model_size_bytes": model.size_bytes if model else 0,
                "endpoint": f"http://{self.host}:{self.port}" if running else "",
                "pid": int(self._process.pid) if running and self._process else None,
                "started_at_unix": self._started_at or None,
                "last_error": self._last_error,
                "allocation": plan.to_dict() if plan else None,
            }


_SERVICE: ModelEngineService | None = None
_SERVICE_LOCK = threading.Lock()


def get_model_engine_service(
    *,
    model_root: Path | None = None,
    inventory_provider: Callable[[], RigInventory] | None = None,
) -> ModelEngineService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            from tools.appliance.hardware_detector import scan_rig_hardware_stable

            root = model_root or Path(os.environ.get("COMPUTEMESH_MODEL_DIR", "/var/lib/computemesh/models"))
            root.mkdir(parents=True, exist_ok=True)
            _SERVICE = ModelEngineService(
                model_root=root,
                inventory_provider=inventory_provider or scan_rig_hardware_stable,
            )
        return _SERVICE
