"""ComputeMesh Architecture Hardening (Part 12)

Enforces invariants:
- "stale provider responses cannot overwrite a newer placement."
- "user cancellation is propagated."
- "billable work maps to accepted execution evidence."
- "recovery never assumes a failed node retained state."
"""

from typing import Any, Dict, List, Optional


class HardeningPart12Error(RuntimeError):
    """Base exception for Part 12 invariant violations."""
    pass


class StaleResponseError(HardeningPart12Error):
    """Raised when a stale provider response attempts to overwrite a newer placement."""
    pass


class CancellationPropagationError(HardeningPart12Error):
    """Raised when cancellation is not successfully propagated to all active workers."""
    pass


class MissingEvidenceError(HardeningPart12Error):
    """Raised when billable work lacks accepted execution evidence."""
    pass


class InvalidRecoveryStateError(HardeningPart12Error):
    """Raised when recovery assumes a failed node retained state."""
    pass


class StaleProviderResponseEnforcer:
    """Enforces: stale provider responses cannot overwrite a newer placement."""

    def enforce_newer_placement(self, current_revision: int, response_revision: int) -> None:
        if response_revision <= current_revision:
            raise StaleResponseError(
                f"Stale provider response (revision {response_revision}) cannot overwrite newer placement (revision {current_revision})."
            )


class UserCancellationPropagator:
    """Enforces: user cancellation is propagated."""

    def propagate_cancellation(self, job_id: str, active_workers: List[str]) -> None:
        if not active_workers:
            # If there are no workers, cancellation has technically reached everyone
            return

        for worker in active_workers:
            if not self._notify_worker(worker, job_id):
                raise CancellationPropagationError(
                    f"Failed to propagate user cancellation for job {job_id} to worker {worker}."
                )

    def _notify_worker(self, worker: str, job_id: str) -> bool:
        """Simulates notifying a worker. Subclasses or tests can override this."""
        return True


class ExecutionEvidenceEnforcer:
    """Enforces: billable work maps to accepted execution evidence."""

    def enforce_billable_work(self, job_id: str, evidence: Optional[Dict[str, Any]]) -> None:
        if not evidence:
            raise MissingEvidenceError(f"Billable work for job {job_id} lacks execution evidence.")

        if "accepted" not in evidence or not evidence["accepted"]:
            raise MissingEvidenceError(f"Billable work for job {job_id} requires accepted execution evidence.")


class RecoveryStateEnforcer:
    """Enforces: recovery never assumes a failed node retained state."""

    def validate_recovery(self, node_state: Dict[str, Any]) -> None:
        if node_state.get("failed", False):
            if node_state.get("retained_state", False):
                raise InvalidRecoveryStateError(
                    "Recovery invariant violated: cannot assume a failed node retained state."
                )
