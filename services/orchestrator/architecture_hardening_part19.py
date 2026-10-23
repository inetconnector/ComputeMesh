"""ComputeMesh Architecture Hardening (Part 19)

Enforces invariants from FAILURE_SEMANTICS.md:
- "ambiguous completion is reconciled before settlement"
- "A duplicate SegmentResult with same attempt/result identity ... creates no duplicate metering."
- "A conflicting duplicate: - integrity incident; - do not settle until investigated."
- "billing is neutral for platform-caused duplicate execution unless policy explicitly assigns cost."
"""

from typing import Any, Dict, Optional, Set
import threading


class HardeningPart19Error(RuntimeError):
    """Base exception for Part 19 invariant violations."""
    pass


class AmbiguousCompletionError(HardeningPart19Error):
    """Raised when settlement is attempted on an ambiguous completion."""
    pass


class DuplicateMeteringError(HardeningPart19Error):
    """Raised when duplicate metering occurs."""
    pass


class ConflictingDuplicateError(HardeningPart19Error):
    """Raised when a conflicting duplicate attempts to settle."""
    pass


class PlatformRetryBillingError(HardeningPart19Error):
    """Raised when platform retry incurs unassigned cost."""
    pass


class AmbiguousCompletionReconciler:
    """Enforces: ambiguous completion is reconciled before settlement."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ambiguous_jobs: Set[str] = set()

    def mark_ambiguous(self, job_id: str) -> None:
        with self._lock:
            self._ambiguous_jobs.add(job_id)

    def mark_reconciled(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._ambiguous_jobs:
                self._ambiguous_jobs.remove(job_id)

    def check_settlement_allowed(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._ambiguous_jobs:
                raise AmbiguousCompletionError(
                    f"Job {job_id} has ambiguous completion and must be reconciled before settlement."
                )


class DuplicateSegmentResultEnforcer:
    """Enforces: A duplicate SegmentResult ... creates no duplicate metering."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metered_segments: Set[str] = set()

    def record_metering(self, attempt_identity: str, result_identity: str) -> bool:
        """Returns True if metering should proceed, False if duplicate."""
        identity = f"{attempt_identity}::{result_identity}"
        with self._lock:
            if identity in self._metered_segments:
                return False # Duplicate, creates no duplicate metering
            self._metered_segments.add(identity)
            return True


class ConflictingDuplicateEnforcer:
    """Enforces: A conflicting duplicate: integrity incident; do not settle until investigated."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._investigated_incidents: Set[str] = set()
        self._incidents: Set[str] = set()

    def mark_conflicting_duplicate(self, job_id: str) -> None:
        with self._lock:
            self._incidents.add(job_id)

    def mark_investigated(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._incidents:
                self._investigated_incidents.add(job_id)
                self._incidents.remove(job_id)

    def check_settlement_allowed(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._incidents:
                raise ConflictingDuplicateError(
                    f"Job {job_id} has a conflicting duplicate (integrity incident) and cannot settle until investigated."
                )


class PlatformRetryBillingEnforcer:
    """Enforces: billing is neutral for platform-caused duplicate execution unless policy explicitly assigns cost."""
    def __init__(self) -> None:
        pass

    def calculate_billable_cost(self, base_cost: int, is_platform_retry: bool, policy_assigns_cost: bool) -> int:
        if is_platform_retry and not policy_assigns_cost:
            return 0
        return base_cost
