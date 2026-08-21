from datetime import datetime, timedelta, timezone
import base64
import json
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.node_identity import (
    AUTH_METHOD,
    Ed25519ChallengeVerifier,
    NodeAuthProof,
    VerificationKey,
    create_node_auth_proof,
    key_id_from_public_key,
    signing_message,
)
from protocol.node_session import AuthenticationAttempt, NodeHelloInfo


class Resolver:
    def __init__(self, record):
        self.record = record

    def resolve_key(self, node_id, key_id):
        if self.record is None or (node_id, key_id) != (
            self.record.node_id,
            self.record.key_id,
        ):
            raise KeyError("not found")
        return self.record


class NodeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 21, 19, 0, tzinfo=timezone.utc)
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.key_id = key_id_from_public_key(self.public)
        self.hello = NodeHelloInfo(
            agent_version="0.1.0",
            platform="windows-amd64",
            supported_auth_methods=(AUTH_METHOD,),
            capabilities=frozenset({"profile_v1", "benchmark_v1"}),
            node_id="node-1",
        )
        self.record = VerificationKey(
            node_id="node-1",
            principal_id="provider-1",
            key_id=self.key_id,
            public_key=self.public,
        )
        self.verifier = Ed25519ChallengeVerifier(Resolver(self.record))

    def proof(self, **kwargs):
        params = dict(
            private_key=self.private,
            node_id="node-1",
            key_id=self.key_id,
            session_id="session-1",
            challenge="challenge-0123456789abcdef",
            hello=self.hello,
            now=self.now,
        )
        params.update(kwargs)
        return create_node_auth_proof(**params)

    def verify(
        self,
        credential,
        *,
        hello=None,
        session_id="session-1",
        challenge="challenge-0123456789abcdef",
        now=None,
    ):
        return self.verifier.verify(
            session_id=session_id,
            challenge=challenge,
            hello=hello or self.hello,
            attempt=AuthenticationAttempt(AUTH_METHOD, credential),
            now=now or self.now,
        )

    def test_happy_path_returns_bounded_authenticated_session(self):
        result = self.verify(self.proof())
        self.assertTrue(result.authenticated)
        self.assertEqual(result.node_id, "node-1")
        self.assertEqual(result.principal_id, "provider-1")
        self.assertEqual(result.key_id, self.key_id)
        self.assertEqual(result.credential_expires_at, self.now + timedelta(minutes=15))

    def test_proof_is_bound_to_session_and_challenge(self):
        credential = self.proof()
        self.assertFalse(self.verify(credential, session_id="session-other").authenticated)
        self.assertFalse(
            self.verify(credential, challenge="different-challenge-abcdef").authenticated
        )

    def test_proof_authenticates_node_hello_semantics(self):
        credential = self.proof()
        changed = NodeHelloInfo(
            agent_version=self.hello.agent_version,
            platform=self.hello.platform,
            supported_auth_methods=self.hello.supported_auth_methods,
            capabilities=frozenset({"profile_v1"}),
            node_id=self.hello.node_id,
        )
        self.assertFalse(self.verify(credential, hello=changed).authenticated)

    def test_expired_proof_rejected(self):
        credential = self.proof()
        result = self.verify(credential, now=self.now + timedelta(seconds=31))
        self.assertFalse(result.authenticated)
        self.assertIn("expired", result.reason)

    def test_future_proof_outside_skew_rejected(self):
        credential = self.proof(now=self.now + timedelta(seconds=31))
        self.assertFalse(self.verify(credential).authenticated)

    def test_unknown_or_revoked_key_rejected(self):
        unknown = Ed25519ChallengeVerifier(Resolver(None))
        attempt = AuthenticationAttempt(AUTH_METHOD, self.proof())
        result = unknown.verify(
            session_id="session-1",
            challenge="challenge-0123456789abcdef",
            hello=self.hello,
            attempt=attempt,
            now=self.now,
        )
        self.assertFalse(result.authenticated)
        revoked = VerificationKey(
            node_id=self.record.node_id,
            principal_id=self.record.principal_id,
            key_id=self.record.key_id,
            public_key=self.record.public_key,
            active=False,
        )
        result = Ed25519ChallengeVerifier(Resolver(revoked)).verify(
            session_id="session-1",
            challenge="challenge-0123456789abcdef",
            hello=self.hello,
            attempt=attempt,
            now=self.now,
        )
        self.assertFalse(result.authenticated)

    def test_signature_tamper_rejected(self):
        proof = NodeAuthProof.decode(self.proof())
        changed = NodeAuthProof(
            node_id=proof.node_id,
            key_id=proof.key_id,
            issued_at=proof.issued_at,
            expires_at=proof.expires_at,
            signature=bytes([proof.signature[0] ^ 1]) + proof.signature[1:],
        ).encode()
        self.assertFalse(self.verify(changed).authenticated)

    def test_oversized_proof_ttl_rejected_by_verifier(self):
        proof = NodeAuthProof.decode(self.proof())
        issued = proof.issued_at
        expires = issued + 61
        sig = self.private.sign(
            signing_message(
                session_id="session-1",
                challenge="challenge-0123456789abcdef",
                hello=self.hello,
                node_id="node-1",
                key_id=self.key_id,
                issued_at=issued,
                expires_at=expires,
            )
        )
        credential = NodeAuthProof("node-1", self.key_id, issued, expires, sig).encode()
        result = self.verify(credential)
        self.assertFalse(result.authenticated)
        self.assertIn("ttl", result.reason)

    def test_malformed_credential_rejected_without_exception(self):
        result = self.verify("not-a-proof")
        self.assertFalse(result.authenticated)
        self.assertIn("malformed", result.reason)

    def test_malformed_json_field_types_are_denied_not_raised(self):
        document = {
            "v": True,
            "node_id": 123,
            "key_id": self.key_id,
            "issued_at": int(self.now.timestamp()),
            "expires_at": int(self.now.timestamp()) + 30,
            "signature": "A" * 86,
        }
        raw = json.dumps(document, separators=(",", ":")).encode("ascii")
        credential = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        result = self.verify(credential)
        self.assertFalse(result.authenticated)
        self.assertIn("malformed", result.reason)


if __name__ == "__main__":
    unittest.main()
