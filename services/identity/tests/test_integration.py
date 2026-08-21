from datetime import datetime, timedelta, timezone
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.control import ControlEnvelope
from protocol.node_identity import (
    AUTH_METHOD,
    Ed25519ChallengeVerifier,
    create_node_auth_proof,
)
from protocol.node_session import NodeSession, NodeSessionState
from protocol.session_wire import BenchmarkAcceptanceDecision, NodeSessionWireHandler
from services.identity.store import SQLiteIdentityStore


class NeverReadyPolicy:
    def evaluate(self, **kwargs):
        return BenchmarkAcceptanceDecision(accepted=True, ready=False)


class IdentityWireIntegrationTests(unittest.TestCase):
    def test_enrolled_key_authenticates_through_wire_handler(self):
        now = datetime(2026, 8, 21, 19, 0, tzinfo=timezone.utc)
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteIdentityStore(f"{tmp}/identity.db") as store:
                token = store.create_enrollment_token(
                    "provider-1", expires_at=now + timedelta(minutes=5), now=now
                )
                enrolled = store.enroll(token, public, now=now)
                session = NodeSession.create(
                    "session-1", challenge="challenge-0123456789abcdef"
                )
                handler = NodeSessionWireHandler(
                    session=session,
                    verifier=Ed25519ChallengeVerifier(store),
                    benchmark_policy=NeverReadyPolicy(),
                    control_plane_capabilities={"profile_v1"},
                    required_capabilities={"profile_v1"},
                )
                hello = {
                    "protocol_major": 0,
                    "protocol_minor": 2,
                    "agent_version": "0.1.0",
                    "platform": "linux-amd64",
                    "node_id": enrolled.node_id,
                    "supported_auth_methods": [AUTH_METHOD],
                    "capabilities": ["profile_v1"],
                }
                hello_env = ControlEnvelope(
                    0,
                    2,
                    "NodeHello",
                    "req-hello",
                    "corr",
                    enrolled.node_id,
                    "session-1",
                    now,
                    now + timedelta(minutes=1),
                    0,
                    hello,
                )
                handler.handle(hello_env, now=now)
                proof = create_node_auth_proof(
                    private_key=private,
                    node_id=enrolled.node_id,
                    key_id=enrolled.key_id,
                    session_id=session.session_id,
                    challenge=session.challenge,
                    hello=session.hello_info,
                    now=now,
                )
                auth_env = ControlEnvelope(
                    0,
                    2,
                    "NodeAuthenticate",
                    "req-auth",
                    "corr",
                    enrolled.node_id,
                    "session-1",
                    now,
                    now + timedelta(minutes=1),
                    1,
                    {"method": AUTH_METHOD, "credential": proof},
                )
                result = handler.handle(auth_env, now=now)
                self.assertEqual(result.state, NodeSessionState.AUTHENTICATED)
                self.assertEqual(result.node_id, enrolled.node_id)
                self.assertEqual(result.principal_id, "provider-1")


if __name__ == "__main__":
    unittest.main()
