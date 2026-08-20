from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Generic, TypeVar


class StateMachineError(RuntimeError):
    pass


class StaleRevision(StateMachineError):
    pass


class InvalidTransition(StateMachineError):
    pass


class IdempotencyConflict(StateMachineError):
    pass


class ReservationState(str, Enum):
    CANDIDATE = "CANDIDATE"
    LEASED = "LEASED"
    COMMITTED = "COMMITTED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class JobState(str, Enum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    PLANNING = "PLANNING"
    RESERVING = "RESERVING"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


S = TypeVar("S", bound=Enum)


@dataclass(frozen=True)
class TransitionResult(Generic[S]):
    state: S
    revision: int
    request_id: str
    changed: bool


@dataclass
class RevisionedStateMachine(Generic[S]):
    state: S
    revision: int = 0
    _processed: dict[str, tuple[S, TransitionResult[S]]] = field(default_factory=dict, init=False, repr=False)

    def _apply(self, *, request_id: str, expected_revision: int, target: S, allowed: set[S]) -> TransitionResult[S]:
        if not request_id:
            raise ValueError("request_id is required")

        previous = self._processed.get(request_id)
        if previous is not None:
            previous_target, previous_result = previous
            if previous_target != target:
                raise IdempotencyConflict(
                    f"request_id {request_id!r} was already used for target {previous_target.value}"
                )
            return TransitionResult(
                state=previous_result.state,
                revision=previous_result.revision,
                request_id=request_id,
                changed=False,
            )

        if expected_revision != self.revision:
            raise StaleRevision(f"expected revision {expected_revision}, current revision {self.revision}")

        if target not in allowed:
            raise InvalidTransition(f"cannot transition from {self.state.value} to {target.value}")

        self.state = target
        self.revision += 1
        result = TransitionResult(state=self.state, revision=self.revision, request_id=request_id, changed=True)
        self._processed[request_id] = (target, result)
        return result


_RESERVATION_TRANSITIONS: dict[ReservationState, set[ReservationState]] = {
    ReservationState.CANDIDATE: {ReservationState.LEASED, ReservationState.REJECTED},
    ReservationState.LEASED: {ReservationState.COMMITTED, ReservationState.EXPIRED, ReservationState.RELEASED},
    ReservationState.COMMITTED: {ReservationState.ACTIVE, ReservationState.RELEASED},
    ReservationState.ACTIVE: {ReservationState.RELEASED},
    ReservationState.RELEASED: set(),
    ReservationState.EXPIRED: set(),
    ReservationState.REJECTED: set(),
}


@dataclass
class ReservationStateMachine(RevisionedStateMachine[ReservationState]):
    state: ReservationState = ReservationState.CANDIDATE
    lease_expires_at: datetime | None = None

    def transition(self, *, request_id: str, expected_revision: int, target: ReservationState) -> TransitionResult[ReservationState]:
        result = self._apply(
            request_id=request_id,
            expected_revision=expected_revision,
            target=target,
            allowed=_RESERVATION_TRANSITIONS[self.state],
        )
        if result.changed and target in {ReservationState.RELEASED, ReservationState.EXPIRED, ReservationState.REJECTED}:
            self.lease_expires_at = None
        return result

    def lease(self, *, request_id: str, expected_revision: int, expires_at: datetime) -> TransitionResult[ReservationState]:
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        now = datetime.now(timezone.utc)
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")
        result = self.transition(
            request_id=request_id,
            expected_revision=expected_revision,
            target=ReservationState.LEASED,
        )
        if result.changed:
            self.lease_expires_at = expires_at.astimezone(timezone.utc)
        return result

    def expire_if_due(self, *, request_id: str, expected_revision: int, now: datetime) -> TransitionResult[ReservationState] | None:
        if self.state != ReservationState.LEASED or self.lease_expires_at is None:
            return None
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if now.astimezone(timezone.utc) < self.lease_expires_at:
            return None
        return self.transition(
            request_id=request_id,
            expected_revision=expected_revision,
            target=ReservationState.EXPIRED,
        )


_JOB_FORWARD: dict[JobState, set[JobState]] = {
    JobState.CREATED: {JobState.VALIDATING},
    JobState.VALIDATING: {JobState.PLANNING},
    JobState.PLANNING: {JobState.RESERVING},
    JobState.RESERVING: {JobState.PREPARING},
    JobState.PREPARING: {JobState.RUNNING},
    JobState.RUNNING: {JobState.VERIFYING},
    JobState.VERIFYING: {JobState.COMPLETED},
    JobState.COMPLETED: {JobState.SETTLED, JobState.REFUNDED},
    JobState.SETTLED: {JobState.REFUNDED},
    JobState.CANCELLED: set(),
    JobState.FAILED: set(),
    JobState.REFUNDED: set(),
}

_JOB_CANCELLABLE = {
    JobState.CREATED,
    JobState.VALIDATING,
    JobState.PLANNING,
    JobState.RESERVING,
    JobState.PREPARING,
    JobState.RUNNING,
    JobState.VERIFYING,
}

_JOB_FAILABLE = set(_JOB_CANCELLABLE)


@dataclass
class JobStateMachine(RevisionedStateMachine[JobState]):
    state: JobState = JobState.CREATED

    def transition(self, *, request_id: str, expected_revision: int, target: JobState) -> TransitionResult[JobState]:
        allowed = set(_JOB_FORWARD[self.state])
        if self.state in _JOB_CANCELLABLE:
            allowed.add(JobState.CANCELLED)
        if self.state in _JOB_FAILABLE:
            allowed.add(JobState.FAILED)
        return self._apply(
            request_id=request_id,
            expected_revision=expected_revision,
            target=target,
            allowed=allowed,
        )
