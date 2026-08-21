from datetime import datetime, timedelta, timezone
import unittest

from protocol.node_session import (
    AuthenticationAttempt,
    AuthenticationDecision,
    AuthenticationExpired,
    AuthenticationFailed,
    CapabilityMismatch,
    NodeHelloInfo,
    NodeSession,
    NodeSessionState,
    ProfileMismatch,
    ProtocolVersionMismatch,
    SessionTransitionError,
)


class FakeVerifier:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def verify(self, **kwargs):
        self.calls.append(kwargs)
        return self.decision


class NodeSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
        self.hello = NodeHelloInfo(
            agent_version="0.0.1",
            platform="windows-amd64",
            supported_auth_methods=("test-proof",),
            capabilities=frozenset({"profile_v1", "benchmark_v1", "reservation_v1"}),
            node_id="node-1",
        )

    def session(self):
        return NodeSession.create("session-1", challenge="challenge-0123456789abcdef")

    def verifier(self, *, expires=None, authenticated=True, node_id="node-1"):
        return FakeVerifier(
            AuthenticationDecision(
                authenticated=authenticated,
                node_id=node_id if authenticated else None,
                principal_id="provider-1" if authenticated else None,
                credential_expires_at=(expires or self.now + timedelta(minutes=5)) if authenticated else None,
                key_id="key-1" if authenticated else None,
                reason=None if authenticated else "bad proof",
            )
        )

    def authenticate(self, session):
        session.receive_hello(self.hello)
        session.authenticate(
            AuthenticationAttempt("test-proof", "credential"),
            self.verifier(),
            now=self.now,
        )

    def test_happy_path_to_ready(self):
        session = self.session()
        self.authenticate(session)
        session.negotiate_capabilities(
            {"profile_v1", "benchmark_v1", "other"},
            required={"profile_v1"},
            now=self.now,
        )
        session.sync_profile(7, now=self.now)
        result = session.accept_benchmark_status(
            profile_revision=7, accepted=True, now=self.now
        )
        self.assertEqual(result.state, NodeSessionState.READY)
        self.assertEqual(result.revision, 5)
        self.assertEqual(
            result.negotiated_capabilities,
            frozenset({"profile_v1", "benchmark_v1"}),
        )

    def test_auth_verifier_receives_session_and_challenge(self):
        session = self.session()
        session.receive_hello(self.hello)
        verifier = self.verifier()
        session.authenticate(
            AuthenticationAttempt("test-proof", "credential"),
            verifier,
            now=self.now,
        )
        self.assertEqual(verifier.calls[0]["session_id"], "session-1")
        self.assertEqual(verifier.calls[0]["challenge"], session.challenge)

    def test_failed_auth_does_not_advance(self):
        session = self.session()
        session.receive_hello(self.hello)
        with self.assertRaises(AuthenticationFailed):
            session.authenticate(
                AuthenticationAttempt("test-proof", "bad"),
                self.verifier(authenticated=False),
                now=self.now,
            )
        self.assertEqual(session.state, NodeSessionState.HELLO_RECEIVED)
        self.assertEqual(session.revision, 1)

    def test_expired_credential_rejected(self):
        session = self.session()
        session.receive_hello(self.hello)
        with self.assertRaises(AuthenticationExpired):
            session.authenticate(
                AuthenticationAttempt("test-proof", "x"),
                self.verifier(expires=self.now - timedelta(seconds=1)),
                now=self.now,
            )

    def test_hello_node_id_must_match_authenticated_node(self):
        session = self.session()
        session.receive_hello(self.hello)
        with self.assertRaises(AuthenticationFailed):
            session.authenticate(
                AuthenticationAttempt("test-proof", "x"),
                self.verifier(node_id="node-other"),
                now=self.now,
            )

    def test_unadvertised_auth_method_rejected_before_verifier(self):
        session = self.session()
        session.receive_hello(self.hello)
        verifier = self.verifier()
        with self.assertRaises(AuthenticationFailed):
            session.authenticate(AuthenticationAttempt("other", "x"), verifier, now=self.now)
        self.assertEqual(verifier.calls, [])

    def test_capability_required_missing_rejected_without_state_change(self):
        session = self.session()
        self.authenticate(session)
        with self.assertRaises(CapabilityMismatch):
            session.negotiate_capabilities(
                {"profile_v1"}, required={"reservation_v1"}, now=self.now
            )
        self.assertEqual(session.state, NodeSessionState.AUTHENTICATED)

    def test_cannot_skip_authentication(self):
        session = self.session()
        session.receive_hello(self.hello)
        with self.assertRaises(SessionTransitionError):
            session.sync_profile(1, now=self.now)

    def test_expiry_blocks_later_session_progress(self):
        session = self.session()
        session.receive_hello(self.hello)
        session.authenticate(
            AuthenticationAttempt("test-proof", "x"),
            self.verifier(expires=self.now + timedelta(seconds=1)),
            now=self.now,
        )
        with self.assertRaises(AuthenticationExpired):
            session.negotiate_capabilities(
                {"profile_v1"}, now=self.now + timedelta(seconds=2)
            )
        self.assertEqual(session.state, NodeSessionState.AUTHENTICATED)

    def test_profile_revision_must_match_benchmark_status(self):
        session = self.session()
        self.authenticate(session)
        session.negotiate_capabilities({"profile_v1"}, now=self.now)
        session.sync_profile(2, now=self.now)
        with self.assertRaises(ProfileMismatch):
            session.accept_benchmark_status(
                profile_revision=3, accepted=True, now=self.now
            )
        self.assertEqual(session.state, NodeSessionState.PROFILE_SYNCED)

    def test_drain_and_close(self):
        session = self.session()
        self.authenticate(session)
        session.negotiate_capabilities({"profile_v1"}, now=self.now)
        session.sync_profile(1, now=self.now)
        session.accept_benchmark_status(profile_revision=1, accepted=True, now=self.now)
        self.assertEqual(
            session.drain("provider_request", now=self.now).state,
            NodeSessionState.DRAINING,
        )
        self.assertEqual(session.close().state, NodeSessionState.CLOSED)
        revision = session.revision
        self.assertEqual(session.close().revision, revision)

    def test_external_revocation_can_terminate_session(self):
        session = self.session()
        self.authenticate(session)
        result = session.terminate("credential_revoked")
        self.assertEqual(result.state, NodeSessionState.CLOSED)
        self.assertEqual(result.close_reason, "credential_revoked")

    def test_drain_before_ready_rejected(self):
        session = self.session()
        self.authenticate(session)
        session.negotiate_capabilities({"profile_v1"}, now=self.now)
        session.sync_profile(1, now=self.now)
        with self.assertRaises(SessionTransitionError):
            session.drain("provider_request", now=self.now)

    def test_invalid_hello_is_bounded(self):
        with self.assertRaises(ValueError):
            NodeHelloInfo("v", "p", (), frozenset())

    def test_protocol_major_mismatch_does_not_advance(self):
        session = self.session()
        bad = NodeHelloInfo(
            agent_version="0.0.1",
            platform="linux-amd64",
            supported_auth_methods=("test-proof",),
            capabilities=frozenset(),
            protocol_major=1,
            protocol_minor=0,
        )
        with self.assertRaises(ProtocolVersionMismatch):
            session.receive_hello(bad)
        self.assertEqual(session.state, NodeSessionState.CONNECTED)
        self.assertEqual(session.revision, 0)

    def test_protocol_minor_negotiates_to_local_current(self):
        session = self.session()
        hello = NodeHelloInfo(
            agent_version="0.0.1",
            platform="linux-amd64",
            supported_auth_methods=("test-proof",),
            capabilities=frozenset(),
            protocol_major=0,
            protocol_minor=99,
        )
        result = session.receive_hello(hello)
        self.assertEqual(result.protocol_major, 0)
        self.assertEqual(result.protocol_minor, 2)

    def test_actor_binding_failure_does_not_advance_authentication(self):
        session = self.session()
        session.receive_hello(self.hello)
        with self.assertRaises(AuthenticationFailed):
            session.authenticate(
                AuthenticationAttempt("test-proof", "credential"),
                self.verifier(),
                actor_id="node-other",
                now=self.now,
            )
        self.assertEqual(session.state, NodeSessionState.HELLO_RECEIVED)


if __name__ == "__main__":
    unittest.main()
