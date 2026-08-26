from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.node_session import NodeSessionState, SessionSnapshot
from runtime.llama.job_attestation import _canonical_sha256
from runtime.llama.node_attestation_service import NodeAttestationService
from services.orchestrator.authenticated_attestation_transport import (
    AuthenticatedAttestationTransportError,
    SessionAuthenticatedAttestationTransport,
)


def _request() -> dict:
    value = {
        "schema_version": 1,
        "job_id": "job-1",
        "placement_decision_id": "placement-0123456789abcdef",
        "model_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
        "evidence_sha256": "c" * 64,
        "output_sha256": "d" * 64,
        "expected_nodes": ["node-a", "node-b"],
    }
    value["request_id"] = "execution-attestation-request-" + _canonical_sha256(value)[:16]
    return value


def _snapshot(node_id: str, *, capability: bool = True, expired: bool = False) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=f"session-{node_id}",
        state=NodeSessionState.READY,
        revision=5,
        protocol_major=0,
        protocol_minor=2,
        node_id=node_id,
        principal_id=f"principal-{node_id}",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=datetime.now(timezone.utc) + (timedelta(minutes=-1) if expired else timedelta(minutes=10)),
        negotiated_capabilities=frozenset({"execution_attestation_v1"} if capability else set()),
        profile_revision=1,
        drain_reason=None,
        close_reason=None,
    )


class _Sessions:
    def __init__(self, values): self.values = values
    def get_session(self, node_id): return self.values[node_id]


class _Client:
    def __init__(self, services, *, connected=True):
        self.services = services
        self.connected = connected

    def is_connected(self, node_id):
        return self.connected

    def request(self, *, node_id, message_type, payload, timeout_seconds):
        if message_type != "ExecutionAttestationRequest":
            raise AssertionError(message_type)
        return self.services[node_id].handle(
            authenticated_node_id=node_id,
            session_id=f"session-{node_id}",
            request_session_id=payload["session_id"],
            request_document=payload["request"],
        )


class AuthenticatedAttestationTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        services = {}
        for node in ("node-a", "node-b"):
            key = Ed25519PrivateKey.generate()
            path = Path(self.tmp.name) / f"{node}.key"
            path.write_bytes(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
            services[node] = NodeAttestationService(node_id=node, private_key_path=path)
        self.services = services

    def tearDown(self): self.tmp.cleanup()

    def test_authenticated_ready_session_can_request_local_signature(self):
        transport = SessionAuthenticatedAttestationTransport(
            sessions=_Sessions({"node-a": _snapshot("node-a")}),
            client=_Client(self.services),
        )
        result = transport.request_execution_attestation(
            node_id="node-a", request_document=_request(), timeout_seconds=2.0
        )
        self.assertEqual(result["node_id"], "node-a")
        self.assertEqual(result["job_id"], "job-1")
        self.assertTrue(result["signature"])

    def test_disconnected_session_fails_before_signature_request(self):
        transport = SessionAuthenticatedAttestationTransport(
            sessions=_Sessions({"node-a": _snapshot("node-a")}),
            client=_Client(self.services, connected=False),
        )
        with self.assertRaisesRegex(AuthenticatedAttestationTransportError, "no live persistent"):
            transport.request_execution_attestation(
                node_id="node-a", request_document=_request(), timeout_seconds=2.0
            )

    def test_expired_session_fails_closed(self):
        transport = SessionAuthenticatedAttestationTransport(
            sessions=_Sessions({"node-a": _snapshot("node-a", expired=True)}),
            client=_Client(self.services),
        )
        with self.assertRaisesRegex(AuthenticatedAttestationTransportError, "expired"):
            transport.request_execution_attestation(
                node_id="node-a", request_document=_request(), timeout_seconds=2.0
            )

    def test_missing_capability_fails_closed(self):
        transport = SessionAuthenticatedAttestationTransport(
            sessions=_Sessions({"node-a": _snapshot("node-a", capability=False)}),
            client=_Client(self.services),
        )
        with self.assertRaisesRegex(AuthenticatedAttestationTransportError, "did not negotiate"):
            transport.request_execution_attestation(
                node_id="node-a", request_document=_request(), timeout_seconds=2.0
            )

    def test_session_identity_mismatch_is_rejected(self):
        transport = SessionAuthenticatedAttestationTransport(
            sessions=_Sessions({"node-a": _snapshot("node-b")}),
            client=_Client(self.services),
        )
        with self.assertRaisesRegex(AuthenticatedAttestationTransportError, "identity"):
            transport.request_execution_attestation(
                node_id="node-a", request_document=_request(), timeout_seconds=2.0
            )


if __name__ == "__main__":
    unittest.main()
