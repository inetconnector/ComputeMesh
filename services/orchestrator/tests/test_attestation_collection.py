from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from services.orchestrator.attestation_collection import (
    AttestationCollectionError,
    collect_execution_attestations,
)


REQUEST = {
    "schema_version": 1,
    "request_id": "execution-attestation-request-0123456789abcdef",
    "job_id": "job-123",
    "placement_decision_id": "placement-0123456789abcdef",
    "model_sha256": "a" * 64,
    "runtime_sha256": "b" * 64,
    "evidence_sha256": "c" * 64,
    "output_sha256": "d" * 64,
    "expected_nodes": ["node-a", "node-b"],
}


def _attestation(node_id: str) -> dict:
    return {
        "v": 1,
        "node_id": node_id,
        "key_id": "ed25519:key",
        "job_id": REQUEST["job_id"],
        "placement_decision_id": REQUEST["placement_decision_id"],
        "model_sha256": REQUEST["model_sha256"],
        "runtime_sha256": REQUEST["runtime_sha256"],
        "evidence_sha256": REQUEST["evidence_sha256"],
        "output_sha256": REQUEST["output_sha256"],
        "issued_at": 100,
        "expires_at": 200,
        "signature": "x",
    }


class _Transport:
    def __init__(self, responses=None, failing_node=None):
        self.responses = responses or {node: _attestation(node) for node in REQUEST["expected_nodes"]}
        self.failing_node = failing_node
        self.calls = []

    def request_execution_attestation(self, *, node_id, request_document, timeout_seconds):
        self.calls.append((node_id, request_document["job_id"], timeout_seconds))
        if node_id == self.failing_node:
            raise RuntimeError("offline")
        return self.responses[node_id]


class AttestationCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.request = self.root / "request.json"
        self.request.write_text(json.dumps(REQUEST), encoding="utf-8")
        self.output = self.root / "bundle.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_collects_exact_selected_node_set_in_request_order(self):
        transport = _Transport()
        result = collect_execution_attestations(
            request_path=self.request,
            output_path=self.output,
            transport=transport,
            per_node_timeout_seconds=2,
        )
        self.assertEqual(result.job_id, "job-123")
        self.assertEqual(result.participant_node_ids, ("node-a", "node-b"))
        bundle = json.loads(self.output.read_text())
        self.assertEqual([item["node_id"] for item in bundle["attestations"]], ["node-a", "node-b"])
        self.assertEqual({call[0] for call in transport.calls}, {"node-a", "node-b"})

    def test_partial_failure_does_not_persist_bundle(self):
        with self.assertRaisesRegex(AttestationCollectionError, "node-b attestation request failed"):
            collect_execution_attestations(
                request_path=self.request,
                output_path=self.output,
                transport=_Transport(failing_node="node-b"),
                per_node_timeout_seconds=2,
            )
        self.assertFalse(self.output.exists())

    def test_response_cannot_change_job_binding(self):
        responses = {node: _attestation(node) for node in REQUEST["expected_nodes"]}
        responses["node-b"]["job_id"] = "job-other"
        with self.assertRaisesRegex(AttestationCollectionError, "changed bound field job_id"):
            collect_execution_attestations(
                request_path=self.request,
                output_path=self.output,
                transport=_Transport(responses=responses),
                per_node_timeout_seconds=2,
            )
        self.assertFalse(self.output.exists())

    def test_response_cannot_impersonate_another_node(self):
        responses = {node: _attestation(node) for node in REQUEST["expected_nodes"]}
        responses["node-b"]["node_id"] = "node-a"
        with self.assertRaisesRegex(AttestationCollectionError, "another node"):
            collect_execution_attestations(
                request_path=self.request,
                output_path=self.output,
                transport=_Transport(responses=responses),
                per_node_timeout_seconds=2,
            )


if __name__ == "__main__":
    unittest.main()
