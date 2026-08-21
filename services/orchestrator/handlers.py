from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from protocol.control import (
    ControlEnvelope,
    ProtocolFault,
    StructuredError,
    parse_control_envelope,
)
from protocol.message_contracts import MessageContractError, MessageContractValidator

from .persistence import SQLiteStateStore
from .state_machine import (
    IdempotencyConflict,
    InvalidTransition,
    JobState,
    ReservationState,
    StaleRevision,
)


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    request_id: str | None
    message_type: str | None
    target_id: str | None
    state: str | None = None
    revision: int | None = None
    changed: bool | None = None
    error: StructuredError | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            return {
                "ok": True,
                "request_id": self.request_id,
                "message_type": self.message_type,
                "target_id": self.target_id,
                "state": self.state,
                "revision": self.revision,
                "changed": self.changed,
            }
        return {
            "ok": False,
            "request_id": self.request_id,
            "message_type": self.message_type,
            "target_id": self.target_id,
            "error": self.error.to_dict() if self.error else None,
        }


def _bad_payload(env: ControlEnvelope, message: str) -> ProtocolFault:
    return ProtocolFault(
        StructuredError(
            "INVALID_ARGUMENT",
            "invalid_argument",
            False,
            message,
            env.request_id,
            {},
        )
    )


def _fingerprint(env: ControlEnvelope) -> str:
    canonical = json.dumps(
        {"message_type": env.message_type, "payload": dict(env.payload)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _parse_lease(env: ControlEnvelope) -> datetime:
    raw = env.payload["lease_expires_at"]
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise _bad_payload(env, "lease_expires_at must be RFC3339 date-time") from exc
    if value.tzinfo is None:
        raise _bad_payload(env, "lease_expires_at must include timezone")
    return value.astimezone(timezone.utc)


_JOB_MESSAGE_TARGETS = {
    "ValidateJob": JobState.VALIDATING,
    "PlanJob": JobState.PLANNING,
    "ReserveJob": JobState.RESERVING,
    "PrepareJob": JobState.PREPARING,
    "StartJob": JobState.RUNNING,
    "VerifyJob": JobState.VERIFYING,
    "CompleteJob": JobState.COMPLETED,
    "SettleJob": JobState.SETTLED,
    "CancelJob": JobState.CANCELLED,
    "FailJob": JobState.FAILED,
    "RefundJob": JobState.REFUNDED,
}

_RESERVATION_MESSAGE_TARGETS = {
    "ActivateReservation": ReservationState.ACTIVE,
    "ReleaseReservation": ReservationState.RELEASED,
    "RejectReservation": ReservationState.REJECTED,
}

_MESSAGE_VALIDATOR = MessageContractValidator()


def dispatch_control_envelope(env: ControlEnvelope, store: SQLiteStateStore):
    """Apply one validated control message to durable orchestration state."""
    try:
        _MESSAGE_VALIDATOR.validate(env.message_type, env.payload)
    except KeyError as exc:
        raise ProtocolFault(
            StructuredError(
                "UNSUPPORTED_MESSAGE",
                "incompatible",
                False,
                f"unsupported message_type {env.message_type}",
                env.request_id,
                {"message_type": env.message_type},
            )
        ) from exc
    except MessageContractError as exc:
        raise _bad_payload(env, str(exc)) from exc

    fingerprint = _fingerprint(env)

    if env.message_type == "ReserveCapacity":
        return store.lease_reservation(
            env.target_id,
            request_id=env.request_id,
            expected_revision=env.expected_revision,
            expires_at=_parse_lease(env),
            request_fingerprint=fingerprint,
        )

    if env.message_type == "CommitReservation":
        return store.commit_reservation(
            env.target_id,
            request_id=env.request_id,
            expected_revision=env.expected_revision,
            job_id=str(env.payload["job_id"]),
            stage_id=str(env.payload["stage_id"]),
            request_fingerprint=fingerprint,
        )

    if env.message_type in _RESERVATION_MESSAGE_TARGETS:
        return store.transition_reservation(
            env.target_id,
            request_id=env.request_id,
            expected_revision=env.expected_revision,
            target=_RESERVATION_MESSAGE_TARGETS[env.message_type],
            request_fingerprint=fingerprint,
        )

    if env.message_type in _JOB_MESSAGE_TARGETS:
        return store.transition_job(
            env.target_id,
            request_id=env.request_id,
            expected_revision=env.expected_revision,
            target=_JOB_MESSAGE_TARGETS[env.message_type],
            request_fingerprint=fingerprint,
        )

    raise AssertionError("validated message missing dispatch mapping")


def handle_control_message(
    document: Mapping[str, Any],
    store: SQLiteStateStore,
    *,
    now: datetime | None = None,
) -> ControlResult:
    """Parse, validate, dispatch, and normalize failures into structured errors."""
    env: ControlEnvelope | None = None
    try:
        env = parse_control_envelope(document, now=now)
        result = dispatch_control_envelope(env, store)
        return ControlResult(
            True,
            env.request_id,
            env.message_type,
            env.target_id,
            result.state.value,
            result.revision,
            result.changed,
        )
    except ProtocolFault as exc:
        return ControlResult(
            False,
            exc.error.request_id,
            env.message_type if env else document.get("message_type"),
            env.target_id if env else document.get("target_id"),
            error=exc.error,
        )
    except KeyError as exc:
        error = StructuredError(
            "NOT_FOUND",
            "not_found",
            False,
            str(exc),
            env.request_id if env else None,
            {"target_id": env.target_id if env else None},
        )
    except StaleRevision as exc:
        error = StructuredError(
            "STALE_REVISION",
            "conflict",
            True,
            str(exc),
            env.request_id if env else None,
            {"expected_revision": env.expected_revision if env else None},
        )
    except InvalidTransition as exc:
        error = StructuredError(
            "INVALID_STATE_TRANSITION",
            "conflict",
            False,
            str(exc),
            env.request_id if env else None,
            {},
        )
    except IdempotencyConflict as exc:
        error = StructuredError(
            "IDEMPOTENCY_CONFLICT",
            "conflict",
            False,
            str(exc),
            env.request_id if env else None,
            {},
        )
    except ValueError as exc:
        error = StructuredError(
            "INVALID_ARGUMENT",
            "invalid_argument",
            False,
            str(exc),
            env.request_id if env else None,
            {},
        )

    return ControlResult(
        False,
        error.request_id,
        env.message_type if env else None,
        env.target_id if env else None,
        error=error,
    )
