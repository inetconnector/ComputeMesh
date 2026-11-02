"""Safe read-only projections of durable agent sessions for client APIs."""
from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .session import (
    AgentItem,
    AgentSession,
    AgentSessionStore,
    AgentTurn,
    Approval,
    ApprovalStatus,
    EventPage,
    SessionStatus,
    TurnStatus,
    _redact,
)


class SessionProjectionError(RuntimeError):
    """Base error for a client-facing session projection."""


class SessionProjectionDenied(SessionProjectionError):
    """Raised when the caller does not own the requested session."""


@dataclass(frozen=True)
class SessionProjection:
    """A bounded public view that safely projects metadata without leaking secrets."""

    session_id: str
    agent_id: str
    agent_version: str
    status: str
    environment_type: str
    version: int
    created_at: float
    updated_at: float
    title: str = ""
    model: str = ""
    workspace: str = ""
    branch: str = ""
    worktree: str = ""
    reasoning_effort: str = ""
    mode: str = ""
    pinned: bool = False
    archived: bool = False
    parent_session_id: str | None = None
    fork_from_sequence: int | None = None
    session_kind: str = "primary"
    context_turn_id: str | None = None

    @classmethod
    def from_session(cls, session: AgentSession) -> SessionProjection:
        st = dict(session.state) if hasattr(session, "state") and isinstance(session.state, (dict, Mapping)) else {}
        raw_parent = st.get("parent_session_id")
        raw_fork_seq = st.get("fork_from_sequence")
        raw_ctx_turn = st.get("context_turn_id")
        return cls(
            session_id=session.session_id,
            agent_id=session.agent_id,
            agent_version=session.agent_version,
            status=session.status.value,
            environment_type=session.environment_type,
            version=session.version,
            created_at=session.created_at,
            updated_at=session.updated_at,
            title=str(st.get("title") or ""),
            model=str(st.get("model") or ""),
            workspace=str(st.get("workspace") or ""),
            branch=str(st.get("branch") or ""),
            worktree=str(st.get("worktree") or ""),
            reasoning_effort=str(st.get("reasoning_effort") or ""),
            mode=str(st.get("mode") or ""),
            pinned=bool(st.get("pinned", False)),
            archived=bool(st.get("archived", False)),
            parent_session_id=str(raw_parent) if raw_parent else None,
            fork_from_sequence=int(raw_fork_seq) if raw_fork_seq is not None else None,
            session_kind=str(st.get("session_kind") or "primary"),
            context_turn_id=str(raw_ctx_turn) if raw_ctx_turn else None,
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
            "title": self.title,
            "model": self.model,
            "workspace": self.workspace,
            "branch": self.branch,
            "worktree": self.worktree,
            "reasoning_effort": self.reasoning_effort,
            "mode": self.mode,
            "pinned": self.pinned,
            "archived": self.archived,
            "parent_session_id": self.parent_session_id,
            "fork_from_sequence": self.fork_from_sequence,
            "session_kind": self.session_kind,
            "context_turn_id": self.context_turn_id,
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
        "preview": _redact(dict(approval.preview or {}), max_string=512),
    }


def project_turn(turn: AgentTurn) -> dict[str, Any]:
    """Project a single turn through the canonical projection boundary."""
    return turn.to_dict()


def project_item(item: AgentItem) -> dict[str, Any]:
    """Project a single item with secret redaction on its content payload."""
    return {
        "item_id": item.item_id,
        "session_id": item.session_id,
        "turn_id": item.turn_id,
        "kind": item.kind,
        "content": _redact(dict(item.content)),
        "sequence": item.sequence,
        "created_at": item.created_at,
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
    cursor: str | None = None,
    search: str | None = None,
    status: SessionStatus | str | None = None,
    workspace: str | None = None,
    pinned: bool | None = None,
    archived: bool | None = None,
    parent_session_id: str | None = None,
    session_kind: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    if not is_admin and not str(principal_id or "").strip():
        raise SessionProjectionDenied("an authenticated principal is required")
    sessions, next_cursor, has_more = store.list_sessions_page(
        principal_id=None if is_admin else str(principal_id),
        limit=limit,
        cursor=cursor,
        search=search,
        status=status,
        workspace=workspace,
        pinned=pinned,
        archived=archived,
        parent_session_id=parent_session_id,
        session_kind=session_kind,
    )
    return {
        "schema_version": 1,
        "object": "agent_sessions",
        "sessions": [SessionProjection.from_session(session).to_dict() for session in sessions],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def project_turns(
    store: AgentSessionStore,
    session_id: str,
    *,
    principal_id: str | None,
    statuses: Sequence[TurnStatus | str] | None = None,
    limit: int = 100,
    is_admin: bool = False,
) -> dict[str, Any]:
    session = authorize_session(store, session_id, principal_id=principal_id, is_admin=is_admin)
    turns = store.list_turns(session_id=session.session_id, statuses=statuses, limit=limit)
    return {
        "schema_version": 2,
        "object": "agent_turns",
        "session_id": session.session_id,
        "turns": [project_turn(turn) for turn in turns],
    }


def project_items(
    store: AgentSessionStore,
    session_id: str,
    *,
    principal_id: str | None,
    turn_id: str | None = None,
    after_sequence: int = 0,
    limit: int = 200,
    is_admin: bool = False,
) -> dict[str, Any]:
    session = authorize_session(store, session_id, principal_id=principal_id, is_admin=is_admin)
    page_limit = max(1, min(int(limit), 500))
    cursor = max(0, int(after_sequence))
    items = store.list_items(
        session.session_id,
        turn_id=turn_id,
        after_sequence=cursor,
        limit=page_limit + 1,
    )
    visible = items[:page_limit]
    next_sequence = visible[-1].sequence if visible else cursor
    return {
        "schema_version": 2,
        "object": "agent_items",
        "session_id": session.session_id,
        "items": [project_item(item) for item in visible],
        "next_sequence": next_sequence,
        "has_more": len(items) > page_limit,
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
    result: dict[str, Any] = {
        "schema_version": 1,
        "object": "agent_session_events",
        "session": SessionProjection.from_session(session).to_dict(),
        "events": [event.to_dict() for event in page.events],
        "next_sequence": page.next_sequence,
        "has_more": page.has_more,
        "cursor_gap": page.cursor_gap,
        "latest_sequence": page.latest_sequence,
    }
    if page.gap_reason:
        result["gap_reason"] = page.gap_reason
    return result


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
    if not is_admin and (not principal_id or not hmac.compare_digest(str(principal_id), approval.principal_id)):
        raise SessionProjectionDenied("approval does not belong to the authenticated principal")
    return {"schema_version": 1, "object": "agent_approval", "approval": _approval_dict(approval)}
