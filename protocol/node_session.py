from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, Iterable
import secrets

from .control import CURRENT_PROTOCOL_MINOR, SUPPORTED_PROTOCOL_MAJOR


class NodeSessionError(RuntimeError):
    pass


class SessionTransitionError(NodeSessionError):
    pass


class AuthenticationFailed(NodeSessionError):
    pass


class AuthenticationExpired(NodeSessionError):
    pass


class CapabilityMismatch(NodeSessionError):
    pass


class ProfileMismatch(NodeSessionError):
    pass


class ProtocolVersionMismatch(NodeSessionError):
    pass


class NodeSessionState(str, Enum):
    CONNECTED = "CONNECTED"
    HELLO_RECEIVED = "HELLO_RECEIVED"
    AUTHENTICATED = "AUTHENTICATED"
    CAPABILITIES_NEGOTIATED = "CAPABILITIES_NEGOTIATED"
    PROFILE_SYNCED = "PROFILE_SYNCED"
    READY = "READY"
    DRAINING = "DRAINING"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class NodeHelloInfo:
    agent_version: str
    platform: str
    supported_auth_methods: tuple[str, ...]
    capabilities: frozenset[str]
    node_id: str | None = None
    protocol_major: int = SUPPORTED_PROTOCOL_MAJOR
    protocol_minor: int = CURRENT_PROTOCOL_MINOR

    def __post_init__(self) -> None:
        if isinstance(self.protocol_major, bool) or not isinstance(self.protocol_major, int) or self.protocol_major < 0:
            raise ValueError("protocol_major must be a non-negative integer")
        if isinstance(self.protocol_minor, bool) or not isinstance(self.protocol_minor, int) or self.protocol_minor < 0:
            raise ValueError("protocol_minor must be a non-negative integer")
        if not (1 <= len(self.agent_version) <= 128):
            raise ValueError("agent_version must be 1..128 characters")
        if not (1 <= len(self.platform) <= 128):
            raise ValueError("platform must be 1..128 characters")
        if not self.supported_auth_methods:
            raise ValueError("supported_auth_methods must not be empty")
        if len(self.supported_auth_methods) > 16:
            raise ValueError("too many supported_auth_methods")
        for value in self.supported_auth_methods:
            if not (1 <= len(value) <= 64):
                raise ValueError("invalid auth method")
        if len(self.capabilities) > 256:
            raise ValueError("too many capabilities")
        for value in self.capabilities:
            if not (1 <= len(value) <= 128):
                raise ValueError("invalid capability")
        if self.node_id is not None and not (1 <= len(self.node_id) <= 128):
            raise ValueError("invalid node_id")


@dataclass(frozen=True)
class AuthenticationAttempt:
    method: str
    credential: str

    def __post_init__(self) -> None:
        if not (1 <= len(self.method) <= 64):
            raise ValueError("invalid authentication method")
        if not (1 <= len(self.credential) <= 16384):
            raise ValueError("credential must be bounded and non-empty")


@dataclass(frozen=True)
class AuthenticationDecision:
    authenticated: bool
    node_id: str | None = None
    principal_id: str | None = None
    credential_expires_at: datetime | None = None
    key_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.credential_expires_at is not None and self.credential_expires_at.tzinfo is None:
            raise ValueError("credential_expires_at must be timezone-aware")
        if self.authenticated:
            if not self.node_id or not self.principal_id or self.credential_expires_at is None:
                raise ValueError("authenticated decisions require node_id, principal_id, and expiry")


class AuthenticationVerifier(Protocol):
    """Security boundary injected by the deployment.

    There is deliberately no built-in permissive verifier. Implementations must
    verify the credential against the selected node identity/key lifecycle and
    bind the proof to both session_id and challenge.
    """

    def verify(
        self,
        *,
        session_id: str,
        challenge: str,
        hello: NodeHelloInfo,
        attempt: AuthenticationAttempt,
        now: datetime,
    ) -> AuthenticationDecision: ...


@dataclass(frozen=True)
class SessionSnapshot:
    session_id: str
    state: NodeSessionState
    revision: int
    protocol_major: int | None
    protocol_minor: int | None
    node_id: str | None
    principal_id: str | None
    auth_method: str | None
    credential_expires_at: datetime | None
    negotiated_capabilities: frozenset[str]
    profile_revision: int | None
    drain_reason: str | None
    close_reason: str | None
    key_id: str | None = None


@dataclass
class NodeSession:
    session_id: str
    challenge: str
    state: NodeSessionState = NodeSessionState.CONNECTED
    revision: int = 0
    hello_info: NodeHelloInfo | None = None
    protocol_major: int | None = None
    protocol_minor: int | None = None
    node_id: str | None = None
    principal_id: str | None = None
    auth_method: str | None = None
    credential_expires_at: datetime | None = None
    negotiated_capabilities: frozenset[str] = field(default_factory=frozenset)
    profile_revision: int | None = None
    drain_reason: str | None = None
    close_reason: str | None = None
    key_id: str | None = None

    @classmethod
    def create(cls, session_id: str, *, challenge: str | None = None) -> "NodeSession":
        if not (1 <= len(session_id) <= 128):
            raise ValueError("session_id must be 1..128 characters")
        challenge_value = challenge or secrets.token_urlsafe(32)
        if not (16 <= len(challenge_value) <= 512):
            raise ValueError("challenge must be 16..512 characters")
        return cls(session_id=session_id, challenge=challenge_value)

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self.session_id,
            state=self.state,
            revision=self.revision,
            protocol_major=self.protocol_major,
            protocol_minor=self.protocol_minor,
            node_id=self.node_id,
            principal_id=self.principal_id,
            auth_method=self.auth_method,
            credential_expires_at=self.credential_expires_at,
            negotiated_capabilities=self.negotiated_capabilities,
            profile_revision=self.profile_revision,
            drain_reason=self.drain_reason,
            close_reason=self.close_reason,
            key_id=self.key_id,
        )

    def _require(self, expected: NodeSessionState) -> None:
        if self.state != expected:
            raise SessionTransitionError(
                f"session {self.session_id} is {self.state.value}; expected {expected.value}"
            )

    def _advance(self, target: NodeSessionState) -> SessionSnapshot:
        self.state = target
        self.revision += 1
        return self.snapshot()

    def receive_hello(self, hello: NodeHelloInfo) -> SessionSnapshot:
        self._require(NodeSessionState.CONNECTED)
        if hello.protocol_major != SUPPORTED_PROTOCOL_MAJOR:
            raise ProtocolVersionMismatch(
                f"unsupported protocol major {hello.protocol_major}; supported major is {SUPPORTED_PROTOCOL_MAJOR}"
            )
        self.hello_info = hello
        self.protocol_major = SUPPORTED_PROTOCOL_MAJOR
        self.protocol_minor = min(hello.protocol_minor, CURRENT_PROTOCOL_MINOR)
        return self._advance(NodeSessionState.HELLO_RECEIVED)

    def authenticate(
        self,
        attempt: AuthenticationAttempt,
        verifier: AuthenticationVerifier,
        *,
        actor_id: str | None = None,
        now: datetime | None = None,
    ) -> SessionSnapshot:
        self._require(NodeSessionState.HELLO_RECEIVED)
        assert self.hello_info is not None
        if attempt.method not in self.hello_info.supported_auth_methods:
            raise AuthenticationFailed("authentication method was not advertised by node")
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        decision = verifier.verify(
            session_id=self.session_id,
            challenge=self.challenge,
            hello=self.hello_info,
            attempt=attempt,
            now=now_utc,
        )
        if not decision.authenticated:
            raise AuthenticationFailed(decision.reason or "authentication failed")
        assert decision.credential_expires_at is not None
        expires_at = decision.credential_expires_at.astimezone(timezone.utc)
        if expires_at <= now_utc:
            raise AuthenticationExpired("credential is already expired")
        if self.hello_info.node_id is not None and decision.node_id != self.hello_info.node_id:
            raise AuthenticationFailed("authenticated node_id does not match NodeHello")
        if actor_id is not None and decision.node_id != actor_id:
            raise AuthenticationFailed("authenticated node_id does not match control actor_id")
        self.node_id = decision.node_id
        self.principal_id = decision.principal_id
        self.auth_method = attempt.method
        self.credential_expires_at = expires_at
        self.key_id = decision.key_id
        return self._advance(NodeSessionState.AUTHENTICATED)

    def ensure_auth_valid(self, *, now: datetime | None = None) -> None:
        if self.state in {NodeSessionState.CONNECTED, NodeSessionState.HELLO_RECEIVED, NodeSessionState.CLOSED}:
            raise AuthenticationFailed("session is not authenticated")
        if self.credential_expires_at is None:
            raise AuthenticationFailed("session has no authenticated credential")
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if self.credential_expires_at <= now_utc:
            raise AuthenticationExpired("session credential has expired")

    def negotiate_capabilities(
        self,
        control_plane_capabilities: Iterable[str],
        *,
        required: Iterable[str] = (),
        now: datetime | None = None,
    ) -> SessionSnapshot:
        self._require(NodeSessionState.AUTHENTICATED)
        self.ensure_auth_valid(now=now)
        assert self.hello_info is not None
        server = frozenset(control_plane_capabilities)
        required_set = frozenset(required)
        if len(server) > 256 or len(required_set) > 256:
            raise ValueError("capability sets are bounded to 256 entries")
        if any(not (1 <= len(value) <= 128) for value in server | required_set):
            raise ValueError("invalid capability")
        negotiated = self.hello_info.capabilities & server
        missing = required_set - negotiated
        if missing:
            raise CapabilityMismatch(
                "required capabilities not negotiated: " + ", ".join(sorted(missing))
            )
        self.negotiated_capabilities = negotiated
        return self._advance(NodeSessionState.CAPABILITIES_NEGOTIATED)

    def sync_profile(self, profile_revision: int, *, now: datetime | None = None) -> SessionSnapshot:
        self._require(NodeSessionState.CAPABILITIES_NEGOTIATED)
        self.ensure_auth_valid(now=now)
        if isinstance(profile_revision, bool) or not isinstance(profile_revision, int) or profile_revision < 0:
            raise ValueError("profile_revision must be a non-negative integer")
        self.profile_revision = profile_revision
        return self._advance(NodeSessionState.PROFILE_SYNCED)

    def accept_benchmark_status(
        self,
        *,
        profile_revision: int,
        accepted: bool,
        now: datetime | None = None,
    ) -> SessionSnapshot:
        self._require(NodeSessionState.PROFILE_SYNCED)
        self.ensure_auth_valid(now=now)
        if profile_revision != self.profile_revision:
            raise ProfileMismatch(
                f"benchmark profile revision {profile_revision} does not match synced profile {self.profile_revision}"
            )
        if not accepted:
            raise ProfileMismatch("required benchmark status was not accepted")
        return self._advance(NodeSessionState.READY)

    def drain(self, reason: str, *, now: datetime | None = None) -> SessionSnapshot:
        self._require(NodeSessionState.READY)
        self.ensure_auth_valid(now=now)
        if not (1 <= len(reason) <= 512):
            raise ValueError("drain reason must be 1..512 characters")
        self.drain_reason = reason
        return self._advance(NodeSessionState.DRAINING)

    def terminate(self, reason: str) -> SessionSnapshot:
        if self.state == NodeSessionState.CLOSED:
            return self.snapshot()
        if not (1 <= len(reason) <= 512):
            raise ValueError("close reason must be 1..512 characters")
        self.close_reason = reason
        return self._advance(NodeSessionState.CLOSED)

    def close(self) -> SessionSnapshot:
        return self.terminate("normal_close")
