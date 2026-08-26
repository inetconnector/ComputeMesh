"""ComputeMesh M0 orchestrator reference components."""

from .contracts import ContractAdmission, ContractValidationError, ContractValidator
from .evidence_store import (
    ExecutionEvidenceBinding,
    ExecutionEvidenceBindingError,
    ExecutionEvidenceStore,
)
from .handlers import ControlResult, dispatch_control_envelope, handle_control_message
from .persistence import ReservationBinding, SQLiteStateStore, StateRecord
from .state_machine import (
    IdempotencyConflict,
    InvalidTransition,
    JobState,
    ReservationState,
    StaleRevision,
    TransitionResult,
)

__all__ = [
    "ContractAdmission",
    "ContractValidationError",
    "ContractValidator",
    "ControlResult",
    "dispatch_control_envelope",
    "handle_control_message",
    "ExecutionEvidenceBinding",
    "ExecutionEvidenceBindingError",
    "ExecutionEvidenceStore",
    "IdempotencyConflict",
    "InvalidTransition",
    "JobState",
    "ReservationBinding",
    "ReservationState",
    "SQLiteStateStore",
    "StaleRevision",
    "StateRecord",
    "TransitionResult",
]
