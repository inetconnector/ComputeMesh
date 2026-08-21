from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping, Protocol

from .control import ControlEnvelope
from .node_session import (
    AuthenticationAttempt,
    AuthenticationVerifier,
    CapabilityMismatch,
    NodeHelloInfo,
    NodeSession,
    NodeSessionState,
    ProfileMismatch,
    SessionSnapshot,
    SessionTransitionError,
)
from .session_contracts import SessionMessageContractValidator


class NodeSessionWireError(RuntimeError):
    pass


class UnsupportedSessionMessage(NodeSessionWireError):
    pass


class SessionRevisionMismatch(NodeSessionWireError):
    pass


class SessionActorMismatch(NodeSessionWireError):
    pass


class SessionProtocolMismatch(NodeSessionWireError):
    pass


class SessionMessageIdempotencyConflict(NodeSessionWireError):
    pass


class SessionMessageBindingError(NodeSessionWireError):
    pass


class BenchmarkRejected(NodeSessionWireError):
    pass


@dataclass(frozen=True)
class BenchmarkAcceptanceDecision:
    accepted: bool
    ready: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.ready and not self.accepted:
            raise ValueError("ready benchmark decisions must also be accepted")
        if self.reason is not None and not (1 <= len(self.reason) <= 512):
            raise ValueError("benchmark decision reason must be 1..512 characters")


class BenchmarkAcceptancePolicy(Protocol):
    """Deployment/application policy for deciding benchmark readiness.

    There is deliberately no built-in accept-all implementation. The policy may
    accumulate multiple accepted reports before returning ready=True.
    """

    def evaluate(
        self,
        *,
        report: Mapping[str, Any],
        session: SessionSnapshot,
        now: datetime,
    ) -> BenchmarkAcceptanceDecision: ...


@dataclass(frozen=True)
class _ReplayRecord:
    fingerprint: str
    snapshot: SessionSnapshot


class NodeSessionWireHandler:
    """Bind validated ControlEnvelope messages to NodeSession semantics.

    This is transport-neutral and does not implement enrollment, credential
    issuance, authorization beyond node actor binding, or network security.
    """

    def __init__(
        self,
        *,
        session: NodeSession,
        verifier: AuthenticationVerifier,
        benchmark_policy: BenchmarkAcceptancePolicy,
        control_plane_capabilities: Iterable[str],
        required_capabilities: Iterable[str] = (),
        contracts: SessionMessageContractValidator | None = None,
    ):
        self.session = session
        self.verifier = verifier
        self.benchmark_policy = benchmark_policy
        self.control_plane_capabilities = frozenset(control_plane_capabilities)
        self.required_capabilities = frozenset(required_capabilities)
        self.contracts = contracts or SessionMessageContractValidator()
        if len(self.control_plane_capabilities) > 256 or len(self.required_capabilities) > 256:
            raise ValueError("capability sets are bounded to 256 entries")
        if any(
            not isinstance(value, str) or not (1 <= len(value) <= 128)
            for value in self.control_plane_capabilities | self.required_capabilities
        ):
            raise ValueError("invalid capability")
        self._replays: dict[str, _ReplayRecord] = {}

    @staticmethod
    def _fingerprint(envelope: ControlEnvelope) -> str:
        canonical = json.dumps(
            {
                "protocol_major": envelope.protocol_major,
                "protocol_minor": envelope.protocol_minor,
                "message_type": envelope.message_type,
                "actor_id": envelope.actor_id,
                "target_id": envelope.target_id,
                "expected_revision": envelope.expected_revision,
                "payload": envelope.payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _check_replay(self, envelope: ControlEnvelope, fingerprint: str) -> SessionSnapshot | None:
        prior = self._replays.get(envelope.request_id)
        if prior is None:
            return None
        if prior.fingerprint != fingerprint:
            raise SessionMessageIdempotencyConflict(
                f"request_id {envelope.request_id} was already used with different session semantics"
            )
        return prior.snapshot

    def _require_revision(self, envelope: ControlEnvelope) -> None:
        if envelope.expected_revision != self.session.revision:
            raise SessionRevisionMismatch(
                f"expected session revision {envelope.expected_revision}; current revision is {self.session.revision}"
            )

    def _require_negotiated_protocol(self, envelope: ControlEnvelope) -> None:
        if self.session.protocol_major is None or self.session.protocol_minor is None:
            raise SessionProtocolMismatch("session protocol has not been negotiated")
        if (
            envelope.protocol_major != self.session.protocol_major
            or envelope.protocol_minor != self.session.protocol_minor
        ):
            raise SessionProtocolMismatch(
                "control envelope protocol version does not match negotiated session version"
            )

    def _require_authenticated_actor(self, envelope: ControlEnvelope) -> None:
        if self.session.node_id is None:
            raise SessionActorMismatch("session has no authenticated node actor")
        if envelope.actor_id != self.session.node_id:
            raise SessionActorMismatch(
                f"control actor_id {envelope.actor_id!r} does not match authenticated node_id"
            )

    def handle(
        self,
        envelope: ControlEnvelope,
        *,
        now: datetime | None = None,
    ) -> SessionSnapshot:
        try:
            self.contracts.validate(envelope.message_type, envelope.payload)
        except KeyError as exc:
            raise UnsupportedSessionMessage(envelope.message_type) from exc

        fingerprint = self._fingerprint(envelope)
        replay = self._check_replay(envelope, fingerprint)
        if replay is not None:
            return replay

        self._require_revision(envelope)
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        payload = envelope.payload

        if envelope.message_type == "NodeHello":
            if (
                payload["protocol_major"] != envelope.protocol_major
                or payload["protocol_minor"] != envelope.protocol_minor
            ):
                raise SessionProtocolMismatch(
                    "NodeHello payload protocol version does not match its control envelope"
                )
            snapshot = self.session.receive_hello(
                NodeHelloInfo(
                    agent_version=payload["agent_version"],
                    platform=payload["platform"],
                    supported_auth_methods=tuple(payload["supported_auth_methods"]),
                    capabilities=frozenset(payload["capabilities"]),
                    node_id=payload.get("node_id"),
                    protocol_major=payload["protocol_major"],
                    protocol_minor=payload["protocol_minor"],
                )
            )

        elif envelope.message_type == "NodeAuthenticate":
            self._require_negotiated_protocol(envelope)
            snapshot = self.session.authenticate(
                AuthenticationAttempt(
                    method=payload["method"],
                    credential=payload["credential"],
                ),
                self.verifier,
                actor_id=envelope.actor_id,
                now=now_utc,
            )

        elif envelope.message_type == "CapabilityNegotiation":
            self._require_negotiated_protocol(envelope)
            self._require_authenticated_actor(envelope)
            accepted = frozenset(payload["accepted_capabilities"])
            assert self.session.hello_info is not None
            allowed = self.session.hello_info.capabilities & self.control_plane_capabilities
            unexpected = accepted - allowed
            if unexpected:
                raise CapabilityMismatch(
                    "node accepted capabilities not offered by both peers: "
                    + ", ".join(sorted(unexpected))
                )
            snapshot = self.session.negotiate_capabilities(
                accepted,
                required=self.required_capabilities,
                now=now_utc,
            )

        elif envelope.message_type == "NodeProfileUpdate":
            self._require_negotiated_protocol(envelope)
            self._require_authenticated_actor(envelope)
            if payload["node_id"] != self.session.node_id:
                raise SessionMessageBindingError(
                    "NodeProfileUpdate node_id does not match authenticated node"
                )
            snapshot = self.session.sync_profile(payload["profile_revision"], now=now_utc)

        elif envelope.message_type == "BenchmarkReport":
            self._require_negotiated_protocol(envelope)
            self._require_authenticated_actor(envelope)
            if self.session.state != NodeSessionState.PROFILE_SYNCED:
                raise SessionTransitionError(
                    f"session {self.session.session_id} is {self.session.state.value}; "
                    f"expected {NodeSessionState.PROFILE_SYNCED.value}"
                )
            self.session.ensure_auth_valid(now=now_utc)
            if payload["profile_revision"] != self.session.profile_revision:
                raise ProfileMismatch(
                    f"benchmark profile revision {payload['profile_revision']} does not match "
                    f"synced profile {self.session.profile_revision}"
                )
            decision = self.benchmark_policy.evaluate(
                report=dict(payload),
                session=self.session.snapshot(),
                now=now_utc,
            )
            if not decision.accepted:
                raise BenchmarkRejected(decision.reason or "benchmark report was rejected")
            if decision.ready:
                snapshot = self.session.accept_benchmark_status(
                    profile_revision=payload["profile_revision"],
                    accepted=True,
                    now=now_utc,
                )
            else:
                snapshot = self.session.snapshot()

        elif envelope.message_type == "DrainRequest":
            self._require_negotiated_protocol(envelope)
            self._require_authenticated_actor(envelope)
            snapshot = self.session.drain(payload["reason"], now=now_utc)

        else:
            raise UnsupportedSessionMessage(envelope.message_type)

        self._replays[envelope.request_id] = _ReplayRecord(fingerprint, snapshot)
        return snapshot
