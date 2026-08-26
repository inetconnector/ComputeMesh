from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from protocol.attestation_session_wire import (
    AttestationSessionWireError,
    build_attestation_request_envelope,
    validate_attestation_response_envelope,
)
from protocol.control import ControlEnvelope
from protocol.node_session import NodeSessionState, SessionSnapshot
from runtime.llama.job_attestation import _canonical_sha256


def _request():
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


def _session():
    return SessionSnapshot(
        session_id="session-node-a",
        state=NodeSessionState.READY,
        revision=7,
        protocol_major=0,
        protocol_minor=2,
        node_id="node-a",
        principal_id="principal-a",
        auth_method="computemesh-ed25519-v1",
        credential_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        negotiated_capabilities=frozenset({"execution_attestation_v1"}),
        profile_revision=1,
        drain_reason=None,
        close_reason=None,
    )


def _attestation():
    return {
        "v": 1,
        "node_id": "node-a",
        "key_id": "ed25519:key-a",
        "job_id": "job-1",
        "placement_decision_id": "placement-0123456789abcdef",
        "model_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
        "evidence_sha256": "c" * 64,
        "output_sha256": "d" * 64,
        "issued_at": 1,
        "expires_at": 2,
        "signature": "A" * 86,
    }


class AttestationSessionWireTests(unittest.TestCase):
    def test_request_targets_authenticated_session_node(self):
        req = _request()
        env = build_attestation_request_envelope(
            session=_session(), control_plane_id="control-plane", request_document=req
        )
        self.assertEqual(env.target_id, "node-a")
        self.assertEqual(env.correlation_id, req["request_id"])
        self.assertEqual(env.payload["session_id"], "session-node-a")

    def test_response_must_be_from_same_authenticated_session(self):
        session = _session()
        req = _request()
        payload = {
            "session_id": session.session_id,
            "node_id": "node-a",
            "request_id": req["request_id"],
            "attestation": _attestation(),
        }
        now = datetime.now(timezone.utc)
        env = ControlEnvelope(
            protocol_major=0,
            protocol_minor=2,
            message_type="ExecutionAttestationResponse",
            request_id="wire-response-1",
            correlation_id=req["request_id"],
            actor_id="node-a",
            target_id="control-plane",
            issued_at=now,
            expires_at=now + timedelta(seconds=30),
            expected_revision=session.revision,
            payload=payload,
        )
        result = validate_attestation_response_envelope(
            env, session=session, expected_request_id=req["request_id"]
        )
        self.assertEqual(result["node_id"], "node-a")

    def test_wrong_actor_is_rejected(self):
        session = _session()
        req = _request()
        now = datetime.now(timezone.utc)
        env = ControlEnvelope(
            protocol_major=0, protocol_minor=2,
            message_type="ExecutionAttestationResponse",
            request_id="wire-response-1", correlation_id=req["request_id"],
            actor_id="node-b", target_id="control-plane",
            issued_at=now, expires_at=now + timedelta(seconds=30),
            expected_revision=session.revision,
            payload={"session_id": session.session_id, "node_id": "node-a", "request_id": req["request_id"], "attestation": _attestation()},
        )
        with self.assertRaisesRegex(AttestationSessionWireError, "actor"):
            validate_attestation_response_envelope(env, session=session, expected_request_id=req["request_id"])


if __name__ == "__main__":
    unittest.main()
