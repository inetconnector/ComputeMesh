from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.node_identity import VerificationKey, key_id_from_public_key
from services.gateway.execution_attestation import (
    AttestationClaims,
    ExecutionAttestationError,
    create_execution_attestation,
    verify_execution_attestations,
)


class _Resolver:
    def __init__(self, records):
        self.records = records

    def resolve_key(self, node_id, key_id):
        value = self.records.get((node_id, key_id))
        if value is None or not value.active:
            raise KeyError("unavailable")
        return value


def _public_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


class ExecutionAttestationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
        self.keys = {"node-a": Ed25519PrivateKey.generate(), "node-b": Ed25519PrivateKey.generate()}
        self.records = {}
        for node_id, private in self.keys.items():
            public = _public_bytes(private)
            key_id = key_id_from_public_key(public)
            self.records[(node_id, key_id)] = VerificationKey(
                node_id=node_id,
                principal_id=f"principal-{node_id}",
                key_id=key_id,
                public_key=public,
                active=True,
            )
        self.resolver = _Resolver(self.records)
        self.common = dict(
            job_id="inf-0123456789",
            placement_decision_id="placement-0123456789abcdef",
            model_sha256="a" * 64,
            runtime_sha256="b" * 64,
            evidence_sha256="c" * 64,
            output_sha256="d" * 64,
            issued_at=int(self.now.timestamp()),
            expires_at=int((self.now + timedelta(minutes=2)).timestamp()),
        )

    def _bundle(self):
        attestations = []
        for node_id in ("node-a", "node-b"):
            private = self.keys[node_id]
            public = _public_bytes(private)
            claims = AttestationClaims(
                node_id=node_id,
                key_id=key_id_from_public_key(public),
                **self.common,
            )
            attestations.append(create_execution_attestation(private_key=private, claims=claims))
        return {"schema_version": 1, "attestations": attestations}

    def _write(self, document):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False)
        json.dump(document, tmp)
        tmp.close()
        self.addCleanup(lambda: __import__("pathlib").Path(tmp.name).unlink(missing_ok=True))
        return tmp.name

    def test_two_reserved_nodes_can_attest_one_execution(self):
        path = self._write(self._bundle())
        nodes = verify_execution_attestations(
            path,
            resolver=self.resolver,
            expected_nodes=("node-a", "node-b"),
            now=self.now + timedelta(seconds=30),
            **{key: self.common[key] for key in (
                "job_id", "placement_decision_id", "model_sha256", "runtime_sha256",
                "evidence_sha256", "output_sha256",
            )},
        )
        self.assertEqual(nodes, ("node-a", "node-b"))

    def test_signature_tampering_is_rejected(self):
        bundle = self._bundle()
        bundle["attestations"][0]["output_sha256"] = "e" * 64
        path = self._write(bundle)
        with self.assertRaises(ExecutionAttestationError):
            verify_execution_attestations(
                path,
                resolver=self.resolver,
                expected_nodes=("node-a", "node-b"),
                now=self.now + timedelta(seconds=30),
                **{key: self.common[key] for key in (
                    "job_id", "placement_decision_id", "model_sha256", "runtime_sha256",
                    "evidence_sha256", "output_sha256",
                )},
            )

    def test_missing_participant_is_rejected(self):
        bundle = self._bundle()
        bundle["attestations"] = bundle["attestations"][:1]
        path = self._write(bundle)
        with self.assertRaisesRegex(ExecutionAttestationError, "count"):
            verify_execution_attestations(
                path,
                resolver=self.resolver,
                expected_nodes=("node-a", "node-b"),
                now=self.now + timedelta(seconds=30),
                **{key: self.common[key] for key in (
                    "job_id", "placement_decision_id", "model_sha256", "runtime_sha256",
                    "evidence_sha256", "output_sha256",
                )},
            )

    def test_revoked_or_unavailable_key_is_rejected(self):
        bundle = self._bundle()
        node_a = bundle["attestations"][0]
        record = self.records[("node-a", node_a["key_id"])]
        self.resolver.records[("node-a", node_a["key_id"])] = VerificationKey(
            node_id=record.node_id,
            principal_id=record.principal_id,
            key_id=record.key_id,
            public_key=record.public_key,
            active=False,
        )
        path = self._write(bundle)
        with self.assertRaisesRegex(ExecutionAttestationError, "unknown/revoked"):
            verify_execution_attestations(
                path,
                resolver=self.resolver,
                expected_nodes=("node-a", "node-b"),
                now=self.now + timedelta(seconds=30),
                **{key: self.common[key] for key in (
                    "job_id", "placement_decision_id", "model_sha256", "runtime_sha256",
                    "evidence_sha256", "output_sha256",
                )},
            )


if __name__ == "__main__":
    unittest.main()
