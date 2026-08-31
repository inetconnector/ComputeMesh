"""Local capacity reservation guard for ComputeMesh provider nodes.

Enforces hardware-level concurrency limits, memory limits, and lease expirations
on the provider node to prevent resource over-allocation during active inference jobs.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import secrets
import threading
from typing import Any, Iterator


class CapacityGuardError(RuntimeError):
    """Base error for capacity guard violations."""


class CapacityExceededError(CapacityGuardError):
    """Raised when maximum concurrency or memory capacity is exceeded."""


class InvalidLeaseError(CapacityGuardError):
    """Raised when an invalid or already expired lease is presented."""


@dataclass(frozen=True)
class CapacityReservation:
    reservation_id: str
    lease_id: str
    job_id: str
    node_id: str
    device_id: str
    memory_mb: int
    acquired_at: datetime
    expires_at: datetime
    active: bool = True

    def is_expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return current >= self.expires_at


class LocalCapacityGuard:
    """Thread-safe local capacity and lease manager on the provider node."""

    def __init__(
        self,
        *,
        node_id: str,
        max_concurrent_jobs: int = 1,
        total_memory_mb: int | None = None,
        default_ttl_seconds: int = 60,
    ) -> None:
        if not node_id:
            raise ValueError("node_id must be non-empty text")
        if max_concurrent_jobs < 1:
            raise ValueError("max_concurrent_jobs must be >= 1")
        if total_memory_mb is not None and total_memory_mb < 1:
            raise ValueError("total_memory_mb must be >= 1 if specified")
        if not 1 <= default_ttl_seconds <= 3600:
            raise ValueError("default_ttl_seconds must be between 1 and 3600")

        self.node_id = node_id
        self.max_concurrent_jobs = max_concurrent_jobs
        self.total_memory_mb = total_memory_mb
        self.default_ttl_seconds = default_ttl_seconds
        self._lock = threading.RLock()
        self._reservations: dict[str, CapacityReservation] = {}

    def _prune_expired_locked(self, now: datetime) -> int:
        expired_keys = [
            job_id
            for job_id, res in self._reservations.items()
            if res.is_expired(now)
        ]
        for key in expired_keys:
            del self._reservations[key]
        return len(expired_keys)

    def prune_expired(self) -> int:
        """Explicitly purge expired reservations and return count pruned."""
        now = datetime.now(UTC)
        with self._lock:
            return self._prune_expired_locked(now)

    def acquire(
        self,
        *,
        job_id: str,
        lease_id: str | None = None,
        memory_mb: int = 0,
        ttl_seconds: int | None = None,
        device_id: str = "default",
    ) -> CapacityReservation:
        """Acquire a local execution slot and reserve resources."""
        if not job_id:
            raise ValueError("job_id must be non-empty text")
        if memory_mb < 0:
            raise ValueError("memory_mb cannot be negative")

        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        if not 1 <= ttl <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")

        now = datetime.now(UTC)
        effective_lease_id = lease_id or f"local-lease-{secrets.token_hex(8)}"

        with self._lock:
            self._prune_expired_locked(now)

            if job_id in self._reservations:
                existing = self._reservations[job_id]
                if not existing.is_expired(now):
                    raise CapacityExceededError(f"job '{job_id}' already holds an active reservation")

            # Check concurrency slot limit
            active_count = len(self._reservations)
            if active_count >= self.max_concurrent_jobs:
                raise CapacityExceededError(
                    f"concurrent job limit reached ({active_count}/{self.max_concurrent_jobs})"
                )

            # Check memory limit if configured
            if self.total_memory_mb is not None:
                used_mem = sum(r.memory_mb for r in self._reservations.values())
                if used_mem + memory_mb > self.total_memory_mb:
                    raise CapacityExceededError(
                        f"insufficient local memory: requesting {memory_mb} MB, used {used_mem}/{self.total_memory_mb} MB"
                    )

            reservation = CapacityReservation(
                reservation_id=f"res-{secrets.token_hex(12)}",
                lease_id=effective_lease_id,
                job_id=job_id,
                node_id=self.node_id,
                device_id=device_id,
                memory_mb=memory_mb,
                acquired_at=now,
                expires_at=now + timedelta(seconds=ttl),
                active=True,
            )
            self._reservations[job_id] = reservation
            return reservation

    def release(self, job_id: str) -> bool:
        """Release an active reservation by job_id."""
        with self._lock:
            if job_id in self._reservations:
                del self._reservations[job_id]
                return True
            return False

    def renew(self, job_id: str, additional_seconds: int = 30) -> CapacityReservation:
        """Extend the TTL of an active reservation."""
        if not 1 <= additional_seconds <= 3600:
            raise ValueError("additional_seconds must be between 1 and 3600")

        now = datetime.now(UTC)
        with self._lock:
            self._prune_expired_locked(now)
            existing = self._reservations.get(job_id)
            if existing is None or existing.is_expired(now):
                raise InvalidLeaseError(f"no active reservation found for job '{job_id}' to renew")

            new_expires = max(existing.expires_at, now) + timedelta(seconds=additional_seconds)
            updated = CapacityReservation(
                reservation_id=existing.reservation_id,
                lease_id=existing.lease_id,
                job_id=existing.job_id,
                node_id=existing.node_id,
                device_id=existing.device_id,
                memory_mb=existing.memory_mb,
                acquired_at=existing.acquired_at,
                expires_at=new_expires,
                active=True,
            )
            self._reservations[job_id] = updated
            return updated

    def get_active_reservations(self) -> tuple[CapacityReservation, ...]:
        """Return all current non-expired reservations."""
        now = datetime.now(UTC)
        with self._lock:
            self._prune_expired_locked(now)
            return tuple(self._reservations.values())

    def get_status(self) -> dict[str, Any]:
        """Return current status and metrics."""
        now = datetime.now(UTC)
        with self._lock:
            self._prune_expired_locked(now)
            active_count = len(self._reservations)
            used_mem = sum(r.memory_mb for r in self._reservations.values())
            return {
                "node_id": self.node_id,
                "active_jobs": active_count,
                "max_concurrent_jobs": self.max_concurrent_jobs,
                "available_slots": max(0, self.max_concurrent_jobs - active_count),
                "used_memory_mb": used_mem,
                "total_memory_mb": self.total_memory_mb,
                "available_memory_mb": (
                    max(0, self.total_memory_mb - used_mem)
                    if self.total_memory_mb is not None
                    else None
                ),
            }

    @contextmanager
    def reserve(
        self,
        *,
        job_id: str,
        lease_id: str | None = None,
        memory_mb: int = 0,
        ttl_seconds: int | None = None,
        device_id: str = "default",
    ) -> Iterator[CapacityReservation]:
        """Context manager for automatic acquisition and release."""
        res = self.acquire(
            job_id=job_id,
            lease_id=lease_id,
            memory_mb=memory_mb,
            ttl_seconds=ttl_seconds,
            device_id=device_id,
        )
        try:
            yield res
        finally:
            self.release(job_id)
