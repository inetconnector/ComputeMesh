"""Process-isolated transport for bounded self-hosted environments.

The child process owns the filesystem transport and receives only typed
environment lifecycle/request messages over JSONL. No shell is involved. The
parent enforces a wall-clock deadline and terminates the child on protocol or
timeout failure; POSIX children additionally apply CPU, address-space and
file-size limits, while Windows children use a Job Object for hard memory,
process-count and kill-on-close limits. GPU/device isolation remains outside
this adapter.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .environment import (
    EnvironmentLease,
    EnvironmentRequest,
    EnvironmentSpec,
)


class ProcessSandboxError(RuntimeError):
    """Raised when the isolated workspace process cannot satisfy a request."""


class ProcessSandboxTimeout(ProcessSandboxError):
    """Raised when the child misses its bounded response deadline."""


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _JobBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JobIoCounters(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _JobExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobBasicLimitInformation),
            ("IoInfo", _JobIoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _attach_windows_job(process: subprocess.Popen[str], policy: "ProcessSandboxPolicy") -> Any:
    """Apply hard Windows process and memory limits to the child process."""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.INT,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _JobExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.BasicLimitInformation.ActiveProcessLimit = max(1, int(policy.max_processes))
        info.ProcessMemoryLimit = int(policy.memory_bytes)
        if not kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(error)
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(error)
        return job
    except (OSError, AttributeError, NameError) as exc:
        raise ProcessSandboxError("Windows sandbox job could not be applied") from exc


def _close_windows_job(handle: Any) -> None:
    if os.name != "nt" or not handle:
        return
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(handle)
    except (OSError, AttributeError, NameError):
        return


@dataclass(frozen=True)
class ProcessSandboxPolicy:
    """Bounded process policy used by the workspace child."""

    memory_bytes: int = 512 * 1024 * 1024
    max_processes: int = 32
    max_runtime_seconds: int = 3600
    request_timeout_seconds: float = 30.0
    max_message_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if not 1 <= int(self.memory_bytes) <= 1 << 50:
            raise ValueError("memory_bytes is outside the supported bound")
        if not 1 <= int(self.max_processes) <= 100_000:
            raise ValueError("max_processes is outside the supported bound")
        if not 1 <= int(self.max_runtime_seconds) <= 7 * 24 * 3600:
            raise ValueError("max_runtime_seconds is outside the supported bound")
        if not 0.1 <= float(self.request_timeout_seconds) <= 3600.0:
            raise ValueError("request_timeout_seconds is outside the supported bound")
        if not 1024 <= int(self.max_message_bytes) <= 64 * 1024 * 1024:
            raise ValueError("max_message_bytes is outside the supported bound")


def _spec_payload(spec: EnvironmentSpec) -> dict[str, Any]:
    return {
        "environment_id": spec.environment_id,
        "session_id": spec.session_id,
        "kind": spec.kind.value,
        "node_id": spec.node_id,
        "model_id": spec.model_id,
        "allowed_operations": [operation.value for operation in spec.allowed_operations],
        "allowed_paths": list(spec.allowed_paths),
        "network_allowlist": list(spec.network_allowlist),
        "resources": {
            "cpu_millis": spec.resources.cpu_millis,
            "memory_bytes": spec.resources.memory_bytes,
            "vram_bytes": spec.resources.vram_bytes,
            "max_processes": spec.resources.max_processes,
            "max_runtime_seconds": spec.resources.max_runtime_seconds,
        },
        "lease_seconds": spec.lease_seconds,
    }


def _lease_payload(lease: EnvironmentLease) -> dict[str, Any]:
    return {
        "lease_id": lease.lease_id,
        "environment_id": lease.environment_id,
        "issued_at": lease.issued_at,
        "expires_at": lease.expires_at,
        "revision": lease.revision,
    }


def _lease_from_payload(raw: Any) -> EnvironmentLease:
    if not isinstance(raw, Mapping):
        raise ProcessSandboxError("isolated workspace returned an invalid lease")
    try:
        return EnvironmentLease(
            lease_id=str(raw["lease_id"]),
            environment_id=str(raw["environment_id"]),
            issued_at=float(raw["issued_at"]),
            expires_at=float(raw["expires_at"]),
            revision=int(raw["revision"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProcessSandboxError("isolated workspace returned an invalid lease") from exc


def _request_payload(request: EnvironmentRequest) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "operation": request.operation.value,
        "payload": dict(request.payload),
        "idempotency_key": request.idempotency_key,
    }


class ProcessIsolatedWorkspaceTransport:
    """Environment transport backed by one bounded, shell-free child process."""

    def __init__(
        self,
        root: str | Path,
        *,
        policy: ProcessSandboxPolicy | None = None,
        max_file_bytes: int = 8 * 1024 * 1024,
        allow_mesh: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.policy = policy or ProcessSandboxPolicy()
        self.max_file_bytes = max(1, min(128 * 1024 * 1024, int(max_file_bytes)))
        self.allow_mesh = bool(allow_mesh)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._windows_job_handle: Any = None
        self._closed = False

    def _start(self) -> None:
        if self._closed:
            raise ProcessSandboxError("isolated workspace transport is closed")
        if self._process is not None:
            if self._process.poll() is None:
                return
            self._terminate()
        command = [
            sys.executable,
            "-m",
            "services.mcp.platform.workspace_worker",
            "--root",
            str(self.root),
            "--max-file-bytes",
            str(self.max_file_bytes),
            "--max-runtime-seconds",
            str(self.policy.max_runtime_seconds),
            "--memory-bytes",
            str(self.policy.memory_bytes),
            "--max-processes",
            str(self.policy.max_processes),
        ]
        if self.allow_mesh:
            command.append("--allow-mesh")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parents[3]),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=creation_flags,
                start_new_session=(os.name != "nt"),
            )
            self._windows_job_handle = _attach_windows_job(self._process, self.policy)
        except ProcessSandboxError:
            self._terminate()
            raise
        except OSError as exc:
            self._terminate()
            raise ProcessSandboxError("isolated workspace process could not start") from exc

    def _terminate(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        _close_windows_job(self._windows_job_handle)
        self._windows_job_handle = None
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def _request(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        encoded = json.dumps(
            {"operation": operation, "payload": dict(payload)},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        if len(encoded.encode("utf-8")) > self.policy.max_message_bytes:
            raise ProcessSandboxError("isolated workspace request exceeds the message limit")
        with self._lock:
            self._start()
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise ProcessSandboxError("isolated workspace process is unavailable")
            try:
                process.stdin.write(encoded + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._terminate()
                raise ProcessSandboxError("isolated workspace process disconnected") from exc

            responses: queue.Queue[str | BaseException] = queue.Queue(maxsize=1)

            def read_response() -> None:
                try:
                    line = process.stdout.readline()
                    if not line:
                        responses.put(ProcessSandboxError("isolated workspace process closed the protocol"))
                    else:
                        responses.put(line)
                except BaseException as exc:  # pragma: no cover - platform pipe errors vary
                    responses.put(exc)

            reader = threading.Thread(target=read_response, name="ComputeMesh-workspace-reader", daemon=True)
            reader.start()
            try:
                response = responses.get(timeout=float(self.policy.request_timeout_seconds))
            except queue.Empty:
                self._terminate()
                raise ProcessSandboxTimeout("isolated workspace request exceeded its wall-clock limit")
            if isinstance(response, BaseException):
                self._terminate()
                if isinstance(response, ProcessSandboxError):
                    raise response
                raise ProcessSandboxError("isolated workspace protocol read failed") from response
            if len(response.encode("utf-8")) > self.policy.max_message_bytes:
                self._terminate()
                raise ProcessSandboxError("isolated workspace response exceeds the message limit")
            try:
                decoded = json.loads(response)
            except json.JSONDecodeError as exc:
                self._terminate()
                raise ProcessSandboxError("isolated workspace returned invalid JSON") from exc
            if not isinstance(decoded, Mapping):
                self._terminate()
                raise ProcessSandboxError("isolated workspace returned a non-object response")
            if not bool(decoded.get("ok")):
                raise ProcessSandboxError(str(decoded.get("error") or "isolated workspace operation failed"))
            result = decoded.get("result", {})
            if not isinstance(result, Mapping):
                raise ProcessSandboxError("isolated workspace returned a non-object result")
            return dict(result)

    def prepare(self, spec: EnvironmentSpec) -> EnvironmentLease:
        # The environment declaration may tighten the operator default, never
        # widen it. A transport instance owns one child/environment lifecycle.
        self.policy = ProcessSandboxPolicy(
            memory_bytes=min(int(self.policy.memory_bytes), int(spec.resources.memory_bytes)),
            max_processes=min(int(self.policy.max_processes), int(spec.resources.max_processes)),
            max_runtime_seconds=min(int(self.policy.max_runtime_seconds), int(spec.resources.max_runtime_seconds)),
            request_timeout_seconds=min(float(self.policy.request_timeout_seconds), float(spec.resources.max_runtime_seconds)),
            max_message_bytes=int(self.policy.max_message_bytes),
        )
        result = self._request("prepare", {"spec": _spec_payload(spec)})
        return _lease_from_payload(result.get("lease"))

    def heartbeat(self, lease: EnvironmentLease) -> EnvironmentLease:
        result = self._request("heartbeat", {"lease": _lease_payload(lease)})
        return _lease_from_payload(result.get("lease"))

    def execute(self, lease: EnvironmentLease, request: EnvironmentRequest) -> Mapping[str, Any]:
        result = self._request(
            "execute",
            {"lease": _lease_payload(lease), "request": _request_payload(request)},
        )
        value = result.get("result", {})
        if not isinstance(value, Mapping):
            raise ProcessSandboxError("isolated workspace returned an invalid operation result")
        return dict(value)

    def shutdown(self, lease: EnvironmentLease, *, reason: str) -> None:
        try:
            self._request("shutdown", {"lease": _lease_payload(lease), "reason": str(reason)[:256]})
        finally:
            with self._lock:
                self._terminate()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._terminate()

    def __enter__(self) -> "ProcessIsolatedWorkspaceTransport":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


__all__ = ["ProcessSandboxError", "ProcessSandboxPolicy", "ProcessSandboxTimeout", "ProcessIsolatedWorkspaceTransport"]
