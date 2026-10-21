"""ComputeMesh Architecture Hardening & Fault Tolerance Engine (Part 1).

This module provides deep architectural optimizations, fault tolerance, and strict
enforcement of the core invariants defined in ARCHITECTURE.md:
- Every state-changing command MUST be idempotent or carry an idempotency key.
- Capacity MUST be leased/reserved before job dispatch to avoid placement races.
- Workload admission MUST be model/runtime aware.
"""
from __future__ import annotations

import time
import threading
from typing import Any, Callable, TypeVar, Generic, Optional

T = TypeVar('T')

class HardeningError(RuntimeError):
    """Base exception for architecture hardening violations."""
    pass

class CircuitBreakerOpenError(HardeningError):
    """Raised when an operation is rejected because the circuit breaker is open."""
    pass

class IdempotencyViolationError(HardeningError):
    """Raised when an idempotency key is reused inappropriately."""
    pass

class WorkloadAdmissionError(HardeningError):
    """Raised when workload admission invariants are violated."""
    pass


class MeshCircuitBreaker:
    """Provides fault tolerance by preventing cascading failures across mesh nodes.

    States:
    - CLOSED: Normal operation, requests are allowed.
    - OPEN: Failing too much, requests are immediately rejected.
    - HALF_OPEN: Testing if the underlying service has recovered.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout_sec: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.state = "CLOSED"
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    def record_success(self) -> None:
        """Records a successful operation and resets the circuit breaker if needed."""
        with self._lock:
            self._failure_count = 0
            if self.state != "CLOSED":
                self.state = "CLOSED"

    def record_failure(self) -> None:
        """Records a failed operation and opens the circuit if threshold is reached."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self.state == "HALF_OPEN" or self._failure_count >= self.failure_threshold:
                self.state = "OPEN"

    def is_allowed(self) -> bool:
        """Checks if a request is allowed to proceed."""
        with self._lock:
            if self.state == "CLOSED":
                return True
            if self.state == "OPEN":
                if time.time() - self._last_failure_time >= self.recovery_timeout_sec:
                    self.state = "HALF_OPEN"
                    return True
                return False
            # HALF_OPEN state allows one request to test the waters
            return False

    def execute(self, func: Callable[[], T]) -> T:
        """Executes a function, protected by the circuit breaker."""
        if not self.is_allowed():
            raise CircuitBreakerOpenError("Mesh circuit breaker is OPEN. Operation rejected.")

        try:
            result = func()
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise e


class IdempotencyEnforcer:
    """Strictly enforces the invariant: Every state-changing command MUST be idempotent.

    Maintains a durable cache of executed idempotency keys with a time-to-live (TTL).
    """

    def __init__(self, ttl_sec: float = 3600.0):
        self.ttl_sec = ttl_sec
        self._seen_keys: dict[str, tuple[float, Any]] = {}  # key -> (timestamp, result or 'IN_PROGRESS')
        self._in_progress_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def check_and_record(self, idempotency_key: str, func: Callable[[], T]) -> T:
        """Checks if a key exists; if not, executes func() and records the result.
        If it exists, returns the cached result.
        """
        if not idempotency_key:
            raise IdempotencyViolationError("Idempotency key must not be empty.")

        event_to_wait = None

        with self._lock:
            self._prune_expired()
            if idempotency_key in self._seen_keys:
                _, result = self._seen_keys[idempotency_key]
                if result == 'IN_PROGRESS':
                    event_to_wait = self._in_progress_events[idempotency_key]
                else:
                    return result
            else:
                self._seen_keys[idempotency_key] = (time.time(), 'IN_PROGRESS')
                self._in_progress_events[idempotency_key] = threading.Event()

        if event_to_wait:
            event_to_wait.wait()
            with self._lock:
                _, result = self._seen_keys[idempotency_key]
                return result

        # We are the first to execute this
        try:
            result = func()
        except Exception as e:
            with self._lock:
                del self._seen_keys[idempotency_key]
                event = self._in_progress_events.pop(idempotency_key)
                event.set()
            raise e

        with self._lock:
            self._seen_keys[idempotency_key] = (time.time(), result)
            event = self._in_progress_events.pop(idempotency_key)
            event.set()

        return result

    def _prune_expired(self) -> None:
        """Prunes expired keys from the cache. Internal use, assumes lock is held."""
        now = time.time()
        expired_keys = [k for k, (ts, res) in self._seen_keys.items() if res != 'IN_PROGRESS' and now - ts > self.ttl_sec]
        for k in expired_keys:
            del self._seen_keys[k]


class WorkloadAdmissionGate:
    """Strictly enforces the invariants:
    - Capacity MUST be leased/reserved before job dispatch.
    - Workload admission MUST be model/runtime aware.
    """

    def __init__(self, allowed_models: set[str], max_memory_bytes: int):
        self.allowed_models = allowed_models
        self.max_memory_bytes = max_memory_bytes
        self._active_leases: dict[str, dict[str, Any]] = {} # lease_id -> job specs
        self._used_memory_bytes = 0
        self._lock = threading.Lock()

    def register_lease(self, lease_id: str, model_id: str, memory_required_bytes: int) -> None:
        """Registers a verified lease before workload execution."""
        if not lease_id:
            raise WorkloadAdmissionError("Lease ID must not be empty.")

        if model_id not in self.allowed_models:
            raise WorkloadAdmissionError(f"Model '{model_id}' is not supported by this runtime.")

        with self._lock:
            if lease_id in self._active_leases:
                raise WorkloadAdmissionError(f"Lease ID '{lease_id}' is already registered.")

            if self._used_memory_bytes + memory_required_bytes > self.max_memory_bytes:
                raise WorkloadAdmissionError(
                    f"Model requires {memory_required_bytes} bytes, but only {self.max_memory_bytes - self._used_memory_bytes} bytes available out of {self.max_memory_bytes}."
                )

            self._used_memory_bytes += memory_required_bytes
            self._active_leases[lease_id] = {
                "model_id": model_id,
                "memory_required_bytes": memory_required_bytes,
                "timestamp": time.time()
            }

    def admit_workload(self, lease_id: str, model_id: str) -> bool:
        """Admits a workload ONLY if it holds a matching, pre-registered lease."""
        with self._lock:
            if lease_id not in self._active_leases:
                raise WorkloadAdmissionError(f"Workload rejected: No valid lease found for '{lease_id}'.")

            lease = self._active_leases[lease_id]
            if lease["model_id"] != model_id:
                raise WorkloadAdmissionError(
                    f"Workload rejected: Lease model mismatch ({lease['model_id']} != {model_id})."
                )

            return True

    def release_lease(self, lease_id: str) -> None:
        """Releases a registered lease after workload completion."""
        with self._lock:
            if lease_id in self._active_leases:
                self._used_memory_bytes -= self._active_leases[lease_id]["memory_required_bytes"]
                del self._active_leases[lease_id]
