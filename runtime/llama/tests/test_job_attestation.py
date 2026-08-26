from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from protocol.node_identity import VerificationKey, key_id_from_public_key
from runtime.llama.job_attestation import (
    assemble_attestation_bundle,
    build_attestation_request,
    sign_attestation_request,
)
from services.gateway.execution_attestation import verify_execution_attestations


class _Resolver:
    def __init__(self, records):
        self.records = records

    def resolve_key(self, node_id, key_id):
        try:
            return self.records[(node_id, key_id)]
        except KeyError as exc:
            raise KeyError("unknown") from exc


def _canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _evidence(now: datetime) -> dict:
    output = hashlib.sha256(b"shared output").hexdigest()
    sources = {name: "sha256:" + char * 64 for name, char in zip(("experiment_bundle", "baseline", "shared", "relay"), "1234")}
    comparison = {
        "model_sha256": "a" * 64,
        "prompt_sha256": "5" * 64,
        "exact_output_match": True,
        "match_basis": "output_sha256",
        "shared_over_baseline": {
            "prompt_tokens_per_second": 1.1,
            "predicted_tokens_per_second": 1.2,
            "request_ms": 0.9,
        },
    }
    evidence_id = "shared-run-evidence-" + _canonical({
        "bundle_id": "experiment-bundle-0123456789abcdef",
        "sources": sources,
        "comparison": comparison,
    })[:16]
    return {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "captured_at": now.isoformat().replace("+00:00", "Z"),
        "scope": "m1_two_node_shared_runtime_proof",
        "experiment_bundle_id": "experiment-bundle-0123456789abcdef",
        "placement_decision_id": "placement-0123456789abcdef",
        "model": {"basename": "model.gguf", "size_bytes": 1234, "sha256": "a" * 64},
        "runtime": {"name": "llama.cpp", "version": "build 1"},
        "planner_split": {
            "tensor_split": [16.0, 16.0],
            "layer_ranges": [
                {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 16},
                {"node_id": "node-b", "start_layer": 16, "end_layer_exclusive": 32},
            ],
        },
        "sources": {
            "experiment_bundle": {"file_name": "bundle.json", "document_sha256": sources["experiment_bundle"], "bundle_id": "experiment-bundle-0123456789abcdef"},
            "baseline": {"file_name": "baseline.json", "document_sha256": sources["baseline"], "run_id": "llama-rpc-0123456789abcdef"},
            "shared": {"file_name": "shared.json", "document_sha256": sources["shared"], "run_id": "llama-rpc-fedcba9876543210"},
            "relay": {"file_name": "relay.json", "document_sha256": sources["relay"], "listen": "127.0.0.1:5000", "target": "10.0.0.2:5001"},
        },
        "correctness": {
            "prompt_sha256": "5" * 64,
            "exact_output_match": True,
            "match_basis": "output_sha256",
            "baseline_output_sha256": output,
            "shared_output_sha256": output,
            "baseline_token_ids_sha256": None,
            "shared_token_ids_sha256": None,
        },
        "performance": {
            "baseline_request_ms": 100.0,
            "shared_request_ms": 90.0,
            "baseline_prompt_tokens_per_second": 10.0,
            "shared_prompt_tokens_per_second": 11.0,
            "baseline_predicted_tokens_per_second": 20.0,
            "shared_predicted_tokens_per_second": 24.0,
            "shared_over_baseline": comparison["shared_over_baseline"],
            "relay_setup_elapsed_ms": 1.0,
            "relay_active_elapsed_ms": 80.0,
            "relay_total_elapsed_ms": 81.0,
            "coordinator_to_worker_bytes": 100,
            "worker_to_coordinator_bytes": 200,
            "total_forwarded_bytes": 300,
        },
        "production_scheduling": False,
    }


class JobAttestationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)
        self.evidence_path = self.root / "evidence.json"
        self.evidence_path.write_text(json.dumps(_evidence(self.now)), encoding="utf-8")
        self.request_path = self.root / "request.json"
        self.request_path.write_text(
            json.dumps(build_attestation_request(job_id="job-123", evidence_path=self.evidence_path)),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _key(self, name: str):
        private = Ed25519PrivateKey.generate()
        raw = private.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path = self.root / f"{name}.key"
        path.write_bytes(raw)
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        key_id = key_id_from_public_key(public)
        return path, VerificationKey(node_id=name, principal_id=f"provider-{name}", key_id=key_id, public_key=public)

    def test_request_binds_job_runtime_evidence_and_participants(self):
        doc = build_attestation_request(job_id="job-123", evidence_path=self.evidence_path)
        evidence = json.loads(self.evidence_path.read_text())
        self.assertEqual(doc["job_id"], "job-123")
        self.assertEqual(doc["expected_nodes"], ["node-a", "node-b"])
        self.assertEqual(doc["runtime_sha256"], _canonical(evidence["runtime"]))
        self.assertEqual(doc["evidence_sha256"], hashlib.sha256(self.evidence_path.read_bytes()).hexdigest())

    def test_nodes_sign_locally_and_bundle_verifies(self):
        records = {}
        paths = []
        for node_id in ("node-a", "node-b"):
            key_path, record = self._key(node_id)
            records[(node_id, record.key_id)] = record
            attestation = sign_attestation_request(
                request_path=self.request_path,
                node_id=node_id,
                private_key_path=key_path,
                now=self.now,
            )
            path = self.root / f"{node_id}.json"
            path.write_text(json.dumps(attestation), encoding="utf-8")
            paths.append(path)

        bundle = self.root / "bundle.json"
        assemble_attestation_bundle(
            request_path=self.request_path,
            attestation_paths=paths,
            output_path=bundle,
        )
        request_doc = json.loads(self.request_path.read_text())
        verified = verify_execution_attestations(
            bundle,
            resolver=_Resolver(records),
            expected_nodes=("node-a", "node-b"),
            job_id="job-123",
            placement_decision_id=request_doc["placement_decision_id"],
            model_sha256=request_doc["model_sha256"],
            runtime_sha256=request_doc["runtime_sha256"],
            evidence_sha256=request_doc["evidence_sha256"],
            output_sha256=request_doc["output_sha256"],
            now=self.now,
        )
        self.assertEqual(verified, ("node-a", "node-b"))

    def test_node_cannot_sign_request_for_another_participant(self):
        key_path, _ = self._key("node-c")
        with self.assertRaisesRegex(ValueError, "not an expected participant"):
            sign_attestation_request(
                request_path=self.request_path,
                node_id="node-c",
                private_key_path=key_path,
                now=self.now,
            )


if __name__ == "__main__":
    unittest.main()
