from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping

SUPPORTED_PROTOCOL_MAJOR = 0
CURRENT_PROTOCOL_MINOR = 2
DEFAULT_CLOCK_SKEW = timedelta(seconds=30)

_ID_FIELDS = ("request_id", "correlation_id", "actor_id", "target_id")
_REQUIRED = {
    "protocol_major",
    "protocol_minor",
    "message_type",
    "request_id",
    "correlation_id",
    "actor_id",
    "target_id",
    "issued_at",
    "expires_at",
    "expected_revision",
    "payload",
}
_MESSAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class StructuredError:
    code: str
    category: str
    retryable: bool
    message: str
    request_id: str | None = None
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "retryable": self.retryable,
            "message": self.message,
            "details": dict(self.details or {}),
            "request_id": self.request_id,
        }


class ProtocolFault(ValueError):
    def __init__(self, error: StructuredError):
        super().__init__(error.message)
        self.error = error


def _fault(code: str, category: str, message: str, *, request_id: str | None = None, retryable: bool = False, details: Mapping[str, Any] | None = None) -> ProtocolFault:
    return ProtocolFault(StructuredError(code, category, retryable, message, request_id, details))


def _parse_time(value: Any, field: str, request_id: str | None) -> datetime:
    if not isinstance(value, str):
        raise _fault("INVALID_ARGUMENT", "invalid_argument", f"{field} must be an RFC3339 string", request_id=request_id)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", f"{field} must be RFC3339 date-time", request_id=request_id) from exc
    if parsed.tzinfo is None:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", f"{field} must include a timezone", request_id=request_id)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ControlEnvelope:
    protocol_major: int
    protocol_minor: int
    message_type: str
    request_id: str
    correlation_id: str
    actor_id: str
    target_id: str
    issued_at: datetime
    expires_at: datetime
    expected_revision: int
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_major": self.protocol_major,
            "protocol_minor": self.protocol_minor,
            "message_type": self.message_type,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "expected_revision": self.expected_revision,
            "payload": dict(self.payload),
        }


def parse_control_envelope(document: Mapping[str, Any], *, now: datetime | None = None, clock_skew: timedelta = DEFAULT_CLOCK_SKEW) -> ControlEnvelope:
    """Parse the transport-neutral v0 control envelope and enforce base semantics.

    This intentionally does not authorize the actor or interpret message payloads.
    Those are separate service responsibilities.
    """
    if not isinstance(document, Mapping):
        raise _fault("INVALID_ARGUMENT", "invalid_argument", "control envelope must be an object")

    request_id = document.get("request_id") if isinstance(document.get("request_id"), str) else None
    missing = sorted(_REQUIRED - set(document.keys()))
    if missing:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", f"missing required fields: {', '.join(missing)}", request_id=request_id)
    unknown = sorted(set(document.keys()) - _REQUIRED)
    if unknown:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", f"unknown control-envelope fields: {', '.join(unknown)}", request_id=request_id)

    major = document["protocol_major"]
    minor = document["protocol_minor"]
    if isinstance(major, bool) or not isinstance(major, int) or major < 0:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", "protocol_major must be a non-negative integer", request_id=request_id)
    if isinstance(minor, bool) or not isinstance(minor, int) or minor < 0:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", "protocol_minor must be a non-negative integer", request_id=request_id)
    if major != SUPPORTED_PROTOCOL_MAJOR:
        raise _fault(
            "PROTOCOL_INCOMPATIBLE",
            "incompatible",
            f"unsupported protocol major {major}; supported major is {SUPPORTED_PROTOCOL_MAJOR}",
            request_id=request_id,
            details={"supported_major": SUPPORTED_PROTOCOL_MAJOR, "current_minor": CURRENT_PROTOCOL_MINOR},
        )

    message_type = document["message_type"]
    if not isinstance(message_type, str) or not _MESSAGE_RE.fullmatch(message_type):
        raise _fault("INVALID_ARGUMENT", "invalid_argument", "invalid message_type", request_id=request_id)

    ids: dict[str, str] = {}
    for field in _ID_FIELDS:
        value = document[field]
        if not isinstance(value, str) or not (1 <= len(value) <= 256):
            raise _fault("INVALID_ARGUMENT", "invalid_argument", f"{field} must be a non-empty string up to 256 characters", request_id=request_id)
        ids[field] = value

    expected_revision = document["expected_revision"]
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", "expected_revision must be a non-negative integer", request_id=ids["request_id"])

    payload = document["payload"]
    if not isinstance(payload, Mapping):
        raise _fault("INVALID_ARGUMENT", "invalid_argument", "payload must be an object", request_id=ids["request_id"])

    issued_at = _parse_time(document["issued_at"], "issued_at", ids["request_id"])
    expires_at = _parse_time(document["expires_at"], "expires_at", ids["request_id"])
    if expires_at <= issued_at:
        raise _fault("INVALID_ARGUMENT", "invalid_argument", "expires_at must be later than issued_at", request_id=ids["request_id"])

    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if issued_at > now_utc + clock_skew:
        raise _fault(
            "CLOCK_SKEW",
            "invalid_argument",
            "issued_at is too far in the future",
            request_id=ids["request_id"],
            retryable=True,
            details={"allowed_skew_seconds": int(clock_skew.total_seconds())},
        )
    if expires_at <= now_utc:
        raise _fault(
            "DEADLINE_EXCEEDED",
            "deadline_exceeded",
            "control envelope has expired",
            request_id=ids["request_id"],
            retryable=True,
        )

    return ControlEnvelope(
        protocol_major=major,
        protocol_minor=minor,
        message_type=message_type,
        request_id=ids["request_id"],
        correlation_id=ids["correlation_id"],
        actor_id=ids["actor_id"],
        target_id=ids["target_id"],
        issued_at=issued_at,
        expires_at=expires_at,
        expected_revision=expected_revision,
        payload=dict(payload),
    )
