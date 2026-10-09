"""Safe read-only projections of durable agent sessions for client APIs."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from .session import AgentSession, AgentSessionStore, Approval, ApprovalStatus, EventPage


class SessionProjectionError(RuntimeError):
    """Base error for a client-facing session projection."""


class SessionProjectionDenied(SessionProjectionError):
    """Raised when the caller does not own the requested session."""


@dataclass(frozen=True)
class SessionProjection:
    """A bounded public view that intentionally omits mutable session state."""

    session_id: str
    agent_id: str
    agent_version: str
    status: str
    environment_type: str
    version: int
    created_at: float
    updated_at: float

    @classmethod
    def from_session(cls, session: AgentSession) -> "SessionProjection":
        return cls(
            session_id=session.session_id,
            agent_id=session.agent_id,
            agent_version=session.agent_version,
            status=session.status.value,
            environment_type=session.environment_type,
            version=session.version,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "status": self.status,
            "environment_type": self.environment_type,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _approval_dict(approval: Approval) -> dict[str, Any]:
    """Project an approval without exposing the owning principal."""
    return {
        "approval_id": approval.approval_id,
        "session_id": approval.session_id,
        "turn_id": approval.turn_id,
        "tool_id": approval.tool_id,
        "call_id": approval.call_id,
        "arguments_digest": approval.arguments_digest,
        "status": approval.status.value,
        "expires_at": approval.expires_at,
        "created_at": approval.created_at,
        "resolved_at": approval.resolved_at,
        "resolution_reason": approval.resolution_reason,
    }


def _validate_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value or len(value) > 128 or "/" in value or "\\" in value:
        raise ValueError("invalid session_id")
    return value


def authorize_session(
    store: AgentSessionStore,
    session_id: str,
    *,
    principal_id: str | None,
    is_admin: bool = False,
) -> AgentSession:
    """Load a session and enforce exact principal ownership before projection."""
    session = store.get_session(_validate_session_id(session_id))
    if is_admin:
        return session
    principal = str(principal_id or "").strip()
    owner = str(session.principal_id or "").strip()
    if not principal or not owner or not hmac.compare_digest(principal, owner):
        raise SessionProjectionDenied("session does not belong to the authenticated principal")
    return session


def project_session(
    store: AgentSessionStore,
    session_id: str,
    *,
    principal_id: str | None,
    is_admin: bool = False,
) -> dict[str, Any]:
    session = authorize_session(store, session_id, principal_id=principal_id, is_admin=is_admin)
    return {
        "schema_version": 1,
        "object": "agent_session",
        "session": SessionProjection.from_session(session).to_dict(),
    }


def project_sessions(
    store: AgentSessionStore,
    *,
    principal_id: str | None,
    limit: int = 100,
    is_admin: bool = False,
) -> dict[str, Any]:
    if not is_admin and not str(principal_id or "").strip():
        raise SessionProjectionDenied("an authenticated principal is required")
    sessions = store.list_sessions(
        principal_id=None if is_admin else str(principal_id),
        limit=limit,
    )
    return {
        "schema_version": 1,
        "object": "agent_sessions",
        "sessions": [SessionProjection.from_session(session).to_dict() for session in sessions],
    }


def project_events(
    store: AgentSessionStore,
    session_id: str,
    *,
    principal_id: str | None,
    after_sequence: int = 0,
    limit: int = 100,
    wait_seconds: float = 0.0,
    is_admin: bool = False,
) -> dict[str, Any]:
    session = authorize_session(store, session_id, principal_id=principal_id, is_admin=is_admin)
    page: EventPage = store.read_event_page(
        session.session_id,
        after_sequence=after_sequence,
        limit=limit,
        wait_seconds=wait_seconds,
    )
    return {
        "schema_version": 1,
        "object": "agent_session_events",
        "session": SessionProjection.from_session(session).to_dict(),
        "events": [event.to_dict() for event in page.events],
        "next_sequence": page.next_sequence,
        "has_more": page.has_more,
    }


def project_approvals(
    store: AgentSessionStore,
    *,
    principal_id: str | None,
    session_id: str | None = None,
    status: ApprovalStatus | str | None = None,
    limit: int = 100,
    is_admin: bool = False,
) -> dict[str, Any]:
    if not is_admin and not str(principal_id or "").strip():
        raise SessionProjectionDenied("an authenticated principal is required")
    if session_id is not None:
        authorize_session(store, session_id, principal_id=principal_id, is_admin=is_admin)
    approvals = store.list_approvals(
        principal_id=None if is_admin else str(principal_id),
        session_id=session_id,
        status=status,
        limit=limit,
    )
    return {
        "schema_version": 1,
        "object": "agent_approvals",
        "approvals": [_approval_dict(approval) for approval in approvals],
    }


def project_approval(
    store: AgentSessionStore,
    approval_id: str,
    *,
    principal_id: str | None,
    is_admin: bool = False,
) -> dict[str, Any]:
    approval = store.get_approval(approval_id)
    if not is_admin:
        if not principal_id or not hmac.compare_digest(str(principal_id), approval.principal_id):
            raise SessionProjectionDenied("approval does not belong to the authenticated principal")
    return {"schema_version": 1, "object": "agent_approval", "approval": _approval_dict(approval)}
