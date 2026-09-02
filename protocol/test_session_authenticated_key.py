from datetime import UTC, datetime, timedelta

from protocol.node_session import (
    AuthenticationAttempt,
    AuthenticationDecision,
    NodeHelloInfo,
    NodeSession,
)


class _Verifier:
    def verify(self, *, session_id, challenge, hello, attempt, now):
        return AuthenticationDecision(
            authenticated=True,
            node_id="node-a",
            principal_id="provider-a",
            credential_expires_at=now + timedelta(minutes=5),
            key_id="ed25519:key-a",
        )


def test_authenticated_session_snapshot_retains_verified_key_id() -> None:
    session = NodeSession.create("session-a", challenge="c" * 32)
    session.receive_hello(
        NodeHelloInfo(
            agent_version="test",
            platform="linux",
            supported_auth_methods=("test-auth",),
            capabilities=frozenset(),
            node_id="node-a",
        )
    )
    snapshot = session.authenticate(
        AuthenticationAttempt(method="test-auth", credential="credential"),
        _Verifier(),
        actor_id="node-a",
        now=datetime.now(UTC),
    )
    assert snapshot.key_id == "ed25519:key-a"
    assert session.snapshot().key_id == "ed25519:key-a"
