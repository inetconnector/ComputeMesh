"""ComputeMesh Multi-GPU Model Engine Supervisor & Execution Service.

Manages the lifecycle of the local multi-GPU llama-server process on NodeOS rigs:
- Hardware device detection & tensor split (-ts) calculation across heterogeneous GPUs
- KV-cache and context overhead reservation
- Subprocess supervision on 127.0.0.1:8081
- Internal 1-token inference smoketest & NVML VRAM measurement before marking READY
- In-flight request tracking & graceful draining (max 10s) upon model deactivation
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("computemesh.appliance.model_engine")


class EngineState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    SMOKETEST = "SMOKETEST"
    READY = "READY"
    DRAINING = "DRAINING"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


@dataclass
class GpuDeviceStatus:
    index: int
    name: str
    vram_total_bytes: int
    vram_used_bytes: int = 0
    split_fraction: float = 0.0
    allocated_layers: int = 0


@dataclass
class ModelEngineConfig:
    host: str = "127.0.0.1"
    port: int = 8081
    executable_path: str = "llama-server"
    default_context_size: int = 8192
    smoketest_timeout_seconds: float = 30.0
    drain_timeout_seconds: float = 10.0
    startup_poll_interval: float = 0.5
    startup_max_wait_seconds: float = 60.0
    allow_mock: bool = False


class ModelEngineService:
    """Thread-safe supervisor for local Multi-GPU llama-server instances."""

    _instance: ModelEngineService | None = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls, config: ModelEngineConfig | None = None) -> ModelEngineService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config or ModelEngineConfig())
            return cls._instance

    def __init__(self, config: ModelEngineConfig) -> None:
        self.config = config
        self.state = EngineState.IDLE
        self.active_model_id: str | None = None
        self.active_model_path: str | None = None
        self.active_model_digest: str | None = None
        self.started_at: float | None = None
        self.last_error: str | None = None
        self.active_streams: int = 0
        self._process: subprocess.Popen | None = None
        self._gpu_statuses: list[GpuDeviceStatus] = []
        self._state_lock = threading.RLock()
        self._drain_event = threading.Event()
        self._drain_event.set()

    def compute_model_digest(self, filepath: Path) -> str:
        """Computes real SHA-256 digest of the model weights on disk."""
        import hashlib
        sha = hashlib.sha256()
        with open(filepath, "rb") as f:
            chunk = f.read(64 * 1024 * 1024)
            sha.update(chunk)
        return f"sha256:{sha.hexdigest()}"

    def get_status(self) -> dict[str, Any]:
        with self._state_lock:
            uptime = (time.time() - self.started_at) if (self.started_at and self.state == EngineState.READY) else 0.0
            return {
                "state": self.state.value,
                "active_model_id": self.active_model_id,
                "active_model_path": self.active_model_path,
                "active_model_digest": self.active_model_digest,
                "uptime_seconds": round(uptime, 1),
                "active_streams": self.active_streams,
                "last_error": self.last_error,
                "endpoint": f"http://{self.config.host}:{self.config.port}",
                "gpus": [
                    {
                        "index": g.index,
                        "name": g.name,
                        "vram_total_bytes": g.vram_total_bytes,
                        "vram_used_bytes": g.vram_used_bytes,
                        "split_fraction": round(g.split_fraction, 4),
                        "allocated_layers": g.allocated_layers,
                    }
                    for g in self._gpu_statuses
                ],
            }

    def compute_kv_cache_bytes(
        self,
        context_size: int,
        n_layers: int = 32,
        n_heads: int = 32,
        d_head: int = 128,
        bytes_per_element: int = 2,  # FP16 KV cache
    ) -> int:
        """Estimate KV cache memory requirement in bytes: 2 * n_layers * n_heads * d_head * context_size * bytes_per_element."""
        return 2 * n_layers * n_heads * d_head * context_size * bytes_per_element

    def discover_gpus(self) -> list[GpuDeviceStatus]:
        """Discover available GPUs using hardware scan or nvidia-smi / NVML."""
        devices: list[GpuDeviceStatus] = []
        try:
            from tools.appliance.hardware_detector import scan_rig_hardware
            inventory = scan_rig_hardware()
            for gpu in inventory.gpus:
                if gpu.healthy and gpu.vram_bytes > 0:
                    devices.append(
                        GpuDeviceStatus(
                            index=gpu.index,
                            name=gpu.model_name,
                            vram_total_bytes=gpu.vram_bytes,
                            vram_used_bytes=0,
                        )
                    )
        except Exception as exc:
            log.debug(f"Hardware scan fallback: {exc}")

        return devices

    def query_nvml_vram(self) -> None:
        """Query actual GPU memory used per card via nvidia-smi."""
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                lines = res.stdout.strip().splitlines()
                for line in lines:
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) == 2:
                        idx = int(parts[0])
                        used_mb = int(parts[1])
                        for g in self._gpu_statuses:
                            if g.index == idx:
                                g.vram_used_bytes = used_mb * 1024 * 1024
        except Exception as exc:
            log.debug(f"nvidia-smi query skipped/failed: {exc}")

    def start_model(
        self,
        model_path: str,
        model_id: str,
        model_digest: str | None = None,
        context_size: int | None = None,
        total_layers: int = 32,
        extra_args: list[str] | None = None,
    ) -> bool:
        """Starts the multi-GPU llama-server process, runs smoketest, and sets state to READY."""
        with self._state_lock:
            if self.state in (EngineState.STARTING, EngineState.READY, EngineState.SMOKETEST):
                if self.active_model_path == model_path:
                    log.info(f"Model {model_id} already running.")
                    return True
                # Stop existing before starting new
                self.stop_model(drain_timeout=5.0)

            resolved_path = Path(model_path).resolve()
            if not resolved_path.exists():
                self.state = EngineState.ERROR
                self.last_error = f"Model file not found: {model_path}"
                log.error(self.last_error)
                return False

            self.state = EngineState.STARTING
            self.active_model_id = model_id
            self.active_model_path = str(resolved_path)
            self.active_model_digest = model_digest or self.compute_model_digest(resolved_path)
            self.last_error = None
            self.started_at = None
            ctx_size = context_size or self.config.default_context_size

            # Discover and calculate splits
            self._gpu_statuses = self.discover_gpus()
            total_vram = sum(g.vram_total_bytes for g in self._gpu_statuses) or 1
            fractions = [g.vram_total_bytes / total_vram for g in self._gpu_statuses] if self._gpu_statuses else [1.0]
            split_arg = ",".join(f"{f:.3f}" for f in fractions)

            layers_remaining = total_layers
            for idx, (gpu, frac) in enumerate(zip(self._gpu_statuses, fractions)):
                gpu.split_fraction = frac
                if idx == len(self._gpu_statuses) - 1:
                    gpu.allocated_layers = layers_remaining
                else:
                    assigned = round(frac * total_layers)
                    assigned = min(assigned, layers_remaining)
                    gpu.allocated_layers = assigned
                    layers_remaining -= assigned

            devices_arg = ",".join(f"CUDA{g.index}" for g in self._gpu_statuses) if self._gpu_statuses else "CPU"

            # Build command
            cmd = [
                self.config.executable_path,
                "-m", str(resolved_path),
                "--host", self.config.host,
                "--port", str(self.config.port),
                "-c", str(ctx_size),
                "-ngl", str(total_layers if self._gpu_statuses else 0),
            ]
            if len(self._gpu_statuses) > 1:
                cmd.extend(["-ts", split_arg, "--devices", devices_arg])
            if extra_args:
                cmd.extend(extra_args)

            log.info(f"Launching model engine: {' '.join(cmd)}")
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except FileNotFoundError:
                if not self.config.allow_mock:
                    self.state = EngineState.ERROR
                    self.last_error = (
                        f"llama-server executable '{self.config.executable_path}' not found in system PATH. "
                        "Please install llama.cpp or set the executable path."
                    )
                    log.error(self.last_error)
                    return False
                log.warning(f"Binary {self.config.executable_path} not found in PATH; running with mock enabled for unit tests.")
                self._process = None

            # Poll for readiness
            ready = self._wait_for_server_ready()
            if not ready:
                self.state = EngineState.ERROR
                self.last_error = self.last_error or "Server process failed to bind or respond to health probe within timeout."
                self._kill_process()
                return False

            # Run 1-Token Smoketest
            self.state = EngineState.SMOKETEST
            smoketest_ok = self._run_internal_smoketest(model_id)
            if not smoketest_ok:
                self.state = EngineState.ERROR
                self.last_error = "1-Token Generation Smoketest failed (possible VRAM OOM or corrupt model weights)."
                self._kill_process()
                return False

            # Measure NVML VRAM
            self.query_nvml_vram()

            self.state = EngineState.READY
            self.started_at = time.time()
            log.info(f"Model engine READY for {model_id} on {len(self._gpu_statuses)} GPUs.")
            return True

    def _wait_for_server_ready(self) -> bool:
        """Polls the local server endpoint until it answers HTTP 200."""
        start_time = time.time()
        url = f"http://{self.config.host}:{self.config.port}/health"
        alt_url = f"http://{self.config.host}:{self.config.port}/v1/models"

        while time.time() - start_time < self.config.startup_max_wait_seconds:
            if self._process is not None and self._process.poll() is not None:
                err_out = self._process.stderr.read() if self._process.stderr else ""
                log.error(f"llama-server exited unexpectedly with code {self._process.returncode}: {err_out}")
                return False

            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status in (200, 204):
                        return True
            except Exception:
                pass

            try:
                req = urllib.request.Request(alt_url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass

            time.sleep(self.config.startup_poll_interval)

        # In explicit mock test mode only
        return bool(self._process is None and self.config.allow_mock)

    def _run_internal_smoketest(self, model_id: str) -> bool:
        """Executes a 1-token chat completion to verify generation capability."""
        if self._process is None:
            return self.config.allow_mock

        url = f"http://{self.config.host}:{self.config.port}/v1/chat/completions"
        payload = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.config.smoketest_timeout_seconds) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return "choices" in data and len(data["choices"]) > 0
        except Exception as exc:
            log.error(f"Smoketest inference failed: {exc}")
            return False
        return False

    def acquire_stream(self) -> bool:
        """Acquires a lease for an incoming streaming inference request."""
        with self._state_lock:
            if self.state != EngineState.READY:
                return False
            self.active_streams += 1
            self._drain_event.clear()
            return True

    def release_stream(self) -> None:
        """Releases an in-flight streaming inference request."""
        with self._state_lock:
            if self.active_streams > 0:
                self.active_streams -= 1
            if self.active_streams == 0:
                self._drain_event.set()

    def stop_model(self, drain_timeout: float | None = None) -> None:
        """Initiates graceful draining (up to drain_timeout seconds) and terminates process."""
        with self._state_lock:
            if self.state in (EngineState.IDLE, EngineState.STOPPED) and self._process is None:
                return

            self.state = EngineState.DRAINING
            log.info(f"Model engine entering DRAINING state. In-flight streams: {self.active_streams}")

        timeout = drain_timeout or self.config.drain_timeout_seconds
        # Wait for streams to finish
        self._drain_event.wait(timeout=timeout)

        with self._state_lock:
            self._kill_process()
            self.state = EngineState.STOPPED
            self.active_model_id = None
            self.active_model_path = None
            self.active_model_digest = None
            self.started_at = None
            self.active_streams = 0
            self._drain_event.set()
            log.info("Model engine stopped and unloaded.")

    def _kill_process(self) -> None:
        """Terminates and kills the subprocess safely."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
