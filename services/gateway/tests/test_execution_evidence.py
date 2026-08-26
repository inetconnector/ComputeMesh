from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from services.gateway.execution_evidence import (
    ExecutionEvidenceError,
    verify_shared_execution_evidence,
)
from services.gateway.placement_selection import PlacementSelection
from services.orchestrator.evidence_store import (
    ExecutionEvidenceBindingError,
    ExecutionEvidenceStore,
)
from services.orchestrator.persistence import SQLiteStateStore


MODEL_DIGEST = "a" * 64
OUTPUT = "real runtime output"


def _canonical_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _evidence(captured_at: str) -> dict:
    sources = {
        "experiment_bundle": "sha256:" + "1" * 64,
        "baseline": "sha256:" + "2" * 64,
        "shared": "sha256:" + "3" * 64,
        "relay": "sha256:" + "4" * 64,
    }
    comparison = {
        "model_sha256": MODEL_DIGEST,
        "prompt_sha256": "5" * 64,
        "exact_output_match": True,
        "match_basis": "output_sha256",
        "shared_over_baseline": {
            "prompt_tokens_per_second": 1.1,
            "predicted_tokens_per_second": 1.2,
            "request_ms": 0.9,
        },
    }
    evidence_id = "shared-run-evidence-" + _canonical_digest(
        {
            "bundle_id": "experiment-bundle-0123456789abcdef",
            "sources": sources,
            "comparison": comparison,
        }
    )[:16]
    output_digest = hashlib.sha256(OUTPUT.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "captured_at": captured_at,
        "scope": "m1_two_node_shared_runtime_proof",
        "experiment_bundle_id": "experiment-bundle-0123456789abcdef",
        "placement_decision_id": "placement-0123456789abcdef",
        "model": {"basename": "model.gguf", "size_bytes": 1234, "sha256": MODEL_DIGEST},
        "runtime": {"name": "llama.cpp", "version": "build 1"},
        "planner_split": {
            "tensor_split": [16.0, 16.0],
            "layer_ranges": [
                {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 16},
                {"node_id": "node-b", "start_layer": 16, "end_layer_exclusive": 32},
            ],
        },
        "sources": {
            "experiment_bundle": {
                "file_name": "bundle.json",
                "document_sha256": sources["experiment_bundle"],
                "bundle_id": "experiment-bundle-0123456789abcdef",
            },
            "baseline": {
                "file_name": "baseline.json",
                "document_sha256": sources["baseline"],
                "run_id": "llama-rpc-0123456789abcdef",
            },
            "shared": {
                "file_name": "shared.json",
                "document_sha256": sources["shared"],
                "run_id": "llama-rpc-fedcba9876543210",
            },
            "relay": {
                "file_name": "relay.json",
                "document_sha256": sources["relay"],
                "listen": "127.0.0.1:5000",
                "target": "10.0.0.2:5001",
            },
        },
        "correctness": {
            "prompt_sha256": comparison["prompt_sha256"],
            "exact_output_match": True,
            "match_basis": "output_sha256",
            "baseline_output_sha256": output_digest,
            "shared_output_sha256": output_digest,
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


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "evidence.json"
        self.placement = PlacementSelection(
            decision_id="placement-0123456789abcdef",
            model_id="qwen/qwen2.5-7b-instruct",
            artifact_digest="sha256:" + MODEL_DIGEST,
            provider_node_ids=("node-a", "node-b"),
            layer_ranges=(("node-a", 0, 16), ("node-b", 16, 32)),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, value: dict) -> None:
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_verification_derives_provider_shares_from_layer_ranges(self):
        now = datetime.now(timezone.utc)
        evidence = _evidence(now.isoformat().replace("+00:00", "Z"))
        self._write(evidence)
        verified = verify_shared_execution_evidence(
            self.path,
            placement=self.placement,
            output_text=OUTPUT,
            not_before=now,
            now=now,
        )
        self.assertEqual(verified.provider_shares, (("node-a", 0.5), ("node-b", 0.5)))
        self.assertTrue(verified.document_sha256.startswith("sha256:"))
        self.assertEqual(verified.model_sha256, MODEL_DIGEST)
        self.assertEqual(verified.runtime_sha256, _canonical_digest(evidence["runtime"]))

    def test_output_mismatch_is_rejected(self):
        now = datetime.now(timezone.utc)
        self._write(_evidence(now.isoformat().replace("+00:00", "Z")))
        with self.assertRaisesRegex(ExecutionEvidenceError, "output digest"):
            verify_shared_execution_evidence(
                self.path,
                placement=self.placement,
                output_text="different output",
                not_before=now,
                now=now,
            )

    def test_evidence_document_cannot_be_replayed_to_another_job(self):
        db_path = Path(self.tmp.name) / "state.sqlite3"
        store = SQLiteStateStore(db_path)
        store.ensure_job("job-a")
        store.ensure_job("job-b")
        evidence_store = ExecutionEvidenceStore(store)
        evidence_store.bind(
            job_id="job-a",
            evidence_id="shared-run-evidence-0123456789abcdef",
            document_sha256="sha256:" + "9" * 64,
            placement_decision_id=self.placement.decision_id,
            output_sha256="8" * 64,
            provider_shares=(("node-a", 0.5), ("node-b", 0.5)),
        )
        with self.assertRaises(ExecutionEvidenceBindingError):
            evidence_store.bind(
                job_id="job-b",
                evidence_id="shared-run-evidence-0123456789abcdef",
                document_sha256="sha256:" + "9" * 64,
                placement_decision_id=self.placement.decision_id,
                output_sha256="8" * 64,
                provider_shares=(("node-a", 0.5), ("node-b", 0.5)),
            )
        evidence_store.close()
        store.close()


if __name__ == "__main__":
    unittest.main()
