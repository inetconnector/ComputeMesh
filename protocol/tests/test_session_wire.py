from datetime import datetime, timedelta, timezone
import unittest

from protocol.control import ControlEnvelope
from protocol.node_session import (
    AuthenticationDecision,
    AuthenticationFailed,
    CapabilityMismatch,
    NodeSession,
    NodeSessionState,
    ProfileMismatch,
)
from protocol.session_wire import (
    BenchmarkAcceptanceDecision,
    BenchmarkRejected,
    NodeSessionWireHandler,
    SessionActorMismatch,
    SessionMessageBindingError,
    SessionMessageIdempotencyConflict,
    SessionProtocolMismatch,
    SessionRevisionMismatch,
    UnsupportedSessionMessage,
)


class FakeVerifier:
    def __init__(self, now):
        self.now = now
        self.calls = []

    def verify(self, **kwargs):
        self.calls.append(kwargs)
        return AuthenticationDecision(
            authenticated=True,
            node_id="node-1",
            principal_id="provider-1",
            credential_expires_at=self.now + timedelta(minutes=10),
            key_id="key-1",
        )


class SequencedBenchmarkPolicy:
    def __init__(self, *decisions):
        self.decisions = list(decisions)
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        if self.decisions:
            return self.decisions.pop(0)
        return BenchmarkAcceptanceDecision(accepted=True, ready=True)


class NodeSessionWireTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        self.session = NodeSession.create(
            "session-1", challenge="challenge-0123456789abcdef"
        )
        self.verifier = FakeVerifier(self.now)
        self.policy = SequencedBenchmarkPolicy(
            BenchmarkAcceptanceDecision(accepted=True, ready=True)
        )
        self.handler = NodeSessionWireHandler(
            session=self.session,
            verifier=self.verifier,
            benchmark_policy=self.policy,
            control_plane_capabilities={
                "profile_v1",
                "benchmark_v1",
                "reservation_v1",
            },
            required_capabilities={"profile_v1", "benchmark_v1"},
        )

    def envelope(
        self,
        message_type,
        payload,
        *,
        revision=None,
        request_id=None,
        actor_id="node-1",
        minor=2,
        target_id="session-1",
    ):
        return ControlEnvelope(
            protocol_major=0,
            protocol_minor=minor,
            message_type=message_type,
            request_id=request_id or f"req-{message_type}-{revision if revision is not None else self.session.revision}",
            correlation_id="corr-1",
            actor_id=actor_id,
            target_id=target_id,
            issued_at=self.now,
            expires_at=self.now + timedelta(minutes=1),
            expected_revision=self.session.revision if revision is None else revision,
            payload=payload,
        )

    def hello_payload(self, *, minor=2):
        return {
            "protocol_major": 0,
            "protocol_minor": minor,
            "agent_version": "0.0.1",
            "platform": "windows-amd64",
            "node_id": "node-1",
            "supported_auth_methods": ["test-proof"],
            "capabilities": ["profile_v1", "benchmark_v1", "reservation_v1"],
        }

    def profile_payload(self, *, node_id="node-1", revision=7):
        return {
            "schema_version": 1,
            "node_id": node_id,
            "profile_revision": revision,
            "captured_at": "2026-08-21T12:00:00Z",
            "platform": {
                "os": "Windows",
                "release": "10",
                "architecture": "AMD64",
            },
            "cpu": {"model": "CPU", "logical_cores": 8},
            "memory": {"total_bytes": 1024, "available_bytes": 512},
            "devices": [],
            "runtime_capabilities": [],
            "provider_limits": {"draining": False},
            "benchmark_refs": [],
        }

    def report_payload(self, *, revision=7, run_id="run-1"):
        return {
            "schema_version": 1,
            "run_id": run_id,
            "benchmark_name": "llama_cpp_decode",
            "captured_at": "2026-08-21T12:00:30Z",
            "profile_revision": revision,
            "conditions": {"warm_state": "warm"},
            "metrics": {"tokens_per_second": 10.0},
            "raw_samples": [10.0],
        }

    def advance_to_authenticated(self):
        self.handler.handle(self.envelope("NodeHello", self.hello_payload()), now=self.now)
        self.handler.handle(
            self.envelope(
                "NodeAuthenticate",
                {"method": "test-proof", "credential": "proof"},
            ),
            now=self.now,
        )

    def advance_to_profile_synced(self):
        self.advance_to_authenticated()
        self.handler.handle(
            self.envelope(
                "CapabilityNegotiation",
                {"accepted_capabilities": ["profile_v1", "benchmark_v1"]},
            ),
            now=self.now,
        )
        self.handler.handle(
            self.envelope("NodeProfileUpdate", self.profile_payload()),
            now=self.now,
        )

    def test_happy_path_binds_wire_messages_to_ready(self):
        self.advance_to_profile_synced()
        result = self.handler.handle(
            self.envelope("BenchmarkReport", self.report_payload()),
            now=self.now,
        )
        self.assertEqual(result.state, NodeSessionState.READY)
        self.assertEqual(result.revision, 5)
        self.assertEqual(result.node_id, "node-1")
        self.assertEqual(
            result.negotiated_capabilities,
            frozenset({"profile_v1", "benchmark_v1"}),
        )
        self.assertEqual(len(self.policy.calls), 1)

    def test_node_hello_payload_version_must_match_envelope(self):
        with self.assertRaises(SessionProtocolMismatch):
            self.handler.handle(
                self.envelope("NodeHello", self.hello_payload(minor=1), minor=2),
                now=self.now,
            )
        self.assertEqual(self.session.state, NodeSessionState.CONNECTED)

    def test_higher_peer_minor_negotiates_down_then_is_enforced(self):
        result = self.handler.handle(
            self.envelope("NodeHello", self.hello_payload(minor=7), minor=7),
            now=self.now,
        )
        self.assertEqual(result.protocol_minor, 2)
        with self.assertRaises(SessionProtocolMismatch):
            self.handler.handle(
                self.envelope(
                    "NodeAuthenticate",
                    {"method": "test-proof", "credential": "proof"},
                    minor=7,
                ),
                now=self.now,
            )

    def test_authentication_binds_control_actor_before_state_advance(self):
        self.handler.handle(self.envelope("NodeHello", self.hello_payload()), now=self.now)
        with self.assertRaises(AuthenticationFailed):
            self.handler.handle(
                self.envelope(
                    "NodeAuthenticate",
                    {"method": "test-proof", "credential": "proof"},
                    actor_id="node-other",
                ),
                now=self.now,
            )
        self.assertEqual(self.session.state, NodeSessionState.HELLO_RECEIVED)

    def test_later_message_actor_must_match_authenticated_node(self):
        self.advance_to_authenticated()
        with self.assertRaises(SessionActorMismatch):
            self.handler.handle(
                self.envelope(
                    "CapabilityNegotiation",
                    {"accepted_capabilities": ["profile_v1", "benchmark_v1"]},
                    actor_id="node-other",
                ),
                now=self.now,
            )
        self.assertEqual(self.session.state, NodeSessionState.AUTHENTICATED)

    def test_stale_expected_revision_is_rejected(self):
        self.advance_to_authenticated()
        with self.assertRaises(SessionRevisionMismatch):
            self.handler.handle(
                self.envelope(
                    "CapabilityNegotiation",
                    {"accepted_capabilities": ["profile_v1", "benchmark_v1"]},
                    revision=1,
                ),
                now=self.now,
            )

    def test_exact_request_replay_returns_original_snapshot(self):
        envelope = self.envelope(
            "NodeHello",
            self.hello_payload(),
            request_id="req-replay",
            revision=0,
        )
        first = self.handler.handle(envelope, now=self.now)
        second = self.handler.handle(envelope, now=self.now)
        self.assertEqual(first, second)
        self.assertEqual(self.session.revision, 1)

    def test_changed_request_id_reuse_is_rejected(self):
        first = self.envelope(
            "NodeHello",
            self.hello_payload(),
            request_id="req-conflict",
            revision=0,
        )
        self.handler.handle(first, now=self.now)
        changed = self.envelope(
            "NodeHello",
            {**self.hello_payload(), "agent_version": "0.0.2"},
            request_id="req-conflict",
            revision=0,
        )
        with self.assertRaises(SessionMessageIdempotencyConflict):
            self.handler.handle(changed, now=self.now)

    def test_capability_ack_cannot_add_unoffered_capability(self):
        self.advance_to_authenticated()
        with self.assertRaises(CapabilityMismatch):
            self.handler.handle(
                self.envelope(
                    "CapabilityNegotiation",
                    {
                        "accepted_capabilities": [
                            "profile_v1",
                            "benchmark_v1",
                            "shell_access",
                        ]
                    },
                ),
                now=self.now,
            )
        self.assertEqual(self.session.state, NodeSessionState.AUTHENTICATED)

    def test_profile_node_id_must_match_authenticated_node(self):
        self.advance_to_authenticated()
        self.handler.handle(
            self.envelope(
                "CapabilityNegotiation",
                {"accepted_capabilities": ["profile_v1", "benchmark_v1"]},
            ),
            now=self.now,
        )
        with self.assertRaises(SessionMessageBindingError):
            self.handler.handle(
                self.envelope(
                    "NodeProfileUpdate",
                    self.profile_payload(node_id="node-other"),
                ),
                now=self.now,
            )

    def test_stale_benchmark_profile_is_rejected_before_policy(self):
        self.advance_to_profile_synced()
        with self.assertRaises(ProfileMismatch):
            self.handler.handle(
                self.envelope("BenchmarkReport", self.report_payload(revision=8)),
                now=self.now,
            )
        self.assertEqual(self.policy.calls, [])

    def test_policy_can_accept_multiple_reports_before_ready(self):
        self.policy.decisions = [
            BenchmarkAcceptanceDecision(accepted=True, ready=False),
            BenchmarkAcceptanceDecision(accepted=True, ready=True),
        ]
        self.advance_to_profile_synced()
        first = self.handler.handle(
            self.envelope(
                "BenchmarkReport",
                self.report_payload(run_id="run-1"),
                request_id="req-bench-1",
                revision=4,
            ),
            now=self.now,
        )
        self.assertEqual(first.state, NodeSessionState.PROFILE_SYNCED)
        self.assertEqual(first.revision, 4)
        second = self.handler.handle(
            self.envelope(
                "BenchmarkReport",
                self.report_payload(run_id="run-2"),
                request_id="req-bench-2",
                revision=4,
            ),
            now=self.now,
        )
        self.assertEqual(second.state, NodeSessionState.READY)
        self.assertEqual(second.revision, 5)

    def test_rejected_benchmark_does_not_advance(self):
        self.policy.decisions = [
            BenchmarkAcceptanceDecision(
                accepted=False,
                ready=False,
                reason="required benchmark missing",
            )
        ]
        self.advance_to_profile_synced()
        with self.assertRaises(BenchmarkRejected):
            self.handler.handle(
                self.envelope("BenchmarkReport", self.report_payload()),
                now=self.now,
            )
        self.assertEqual(self.session.state, NodeSessionState.PROFILE_SYNCED)
        self.assertEqual(self.session.revision, 4)

    def test_drain_request_binds_to_ready_transition(self):
        self.advance_to_profile_synced()
        self.handler.handle(
            self.envelope("BenchmarkReport", self.report_payload()),
            now=self.now,
        )
        result = self.handler.handle(
            self.envelope("DrainRequest", {"reason": "provider_request"}),
            now=self.now,
        )
        self.assertEqual(result.state, NodeSessionState.DRAINING)
        self.assertEqual(result.drain_reason, "provider_request")

    def test_unknown_message_family_is_rejected(self):
        with self.assertRaises(UnsupportedSessionMessage):
            self.handler.handle(
                self.envelope("JobAssignment", {}),
                now=self.now,
            )


if __name__ == "__main__":
    unittest.main()
