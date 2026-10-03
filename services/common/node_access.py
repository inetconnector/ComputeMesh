"""Short-lived browser sessions for owner-authorized remote node views."""
from __future__ import annotations

from dataclasses import dataclass
from http.cookies import SimpleCookie
import secrets
import threading
import time
from typing import Any

NODE_SESSION_COOKIE = "cm_node_session"
NODE_SESSION_TTL_SECONDS = 300


@dataclass(frozen=True)
class NodeSession:
    node_id: str
    owner_id: str
    expires_at: float


_SESSIONS: dict[str, NodeSession] = {}
_LOCK = threading.Lock()


def issue_node_session(node_id: str, owner_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with _LOCK:
        now = time.time()
        for key, session in list(_SESSIONS.items()):
            if session.expires_at <= now:
                _SESSIONS.pop(key, None)
        _SESSIONS[token] = NodeSession(
            node_id=node_id,
            owner_id=owner_id,
            expires_at=now + NODE_SESSION_TTL_SECONDS,
        )
    return token


def get_node_session(headers: Any, node_id: str) -> NodeSession | None:
    raw_cookie = str(headers.get("Cookie", "")) if headers else ""
    cookie = SimpleCookie()
    try:
        cookie.load(raw_cookie)
    except Exception:
        return None
    morsel = cookie.get(NODE_SESSION_COOKIE)
    if morsel is None:
        return None
    with _LOCK:
        session = _SESSIONS.get(morsel.value)
        if session is None or session.expires_at <= time.time() or session.node_id != node_id:
            if session is not None:
                _SESSIONS.pop(morsel.value, None)
            return None
        return session


def node_session_cookie(token: str, *, secure: bool = True) -> str:
    cookie = SimpleCookie()
    cookie[NODE_SESSION_COOKIE] = token
    cookie[NODE_SESSION_COOKIE]["path"] = "/"
    cookie[NODE_SESSION_COOKIE]["httponly"] = True
    cookie[NODE_SESSION_COOKIE]["samesite"] = "Lax"
    cookie[NODE_SESSION_COOKIE]["max-age"] = str(NODE_SESSION_TTL_SECONDS)
    if secure:
        cookie[NODE_SESSION_COOKIE]["secure"] = True
    return cookie[NODE_SESSION_COOKIE].OutputString()
