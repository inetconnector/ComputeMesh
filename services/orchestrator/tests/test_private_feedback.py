from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest

from services.gateway.shared_request_evidence import VerifiedSharedRequestEvidence
from services.orchestrator.private_feedback import PrivateFeedbackError, PrivateOutcomeFeedback


def _verified() -> VerifiedSharedRequestEvidence:
    return VerifiedSharedRequestEvidence(
        evidence_id="shared-request-evidence-0123456789abcdef",
        document_sha256="sha256:" + "a" * 64,
        placement_decision_id="placement-0123456789abcdef",
        model_sha256="b" * 64,
        runtime_sha256="c" * 64,
        output_sha256="d" * 64,
        provider_shares=(("node-a", 0.5), ("node-b", 0.5)),
        captured_at=datetime.now(UTC),
        request_ms=650.0,
        prefill_ms=120.0,
        prefill_tps=200.0,
        decode_ms=500.0,
        decode_tps=50.0,
    )


def _network() -> dict:
    return {
        "metrics": {
            "rtt_ms_p50": 4.0,
            "upload_mbps_p50": 900.0,
            "download_mbps_p50": 800.0,
        }
    }


class PrivateFeedbackTests(unittest.TestCase):
    def test_verified_success_is_durably_enqueued_with_conservative_bandwidth(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "outbox.sqlite3"
            feedback = PrivateOutcomeFeedback(
                endpoint="https://control.example.test/internal/v1/outcomes",
                bearer_token="secret",
                outbox_path=path,
            )
            outcome_id = feedback.enqueue_verified_success(
                model_id="model-a",
                coordinator_node_id="node-a",
                worker_node_id="node-b",
                network_result=_network(),
                verified=_verified(),
            )
            self.assertEqual(outcome_id, "outcome-shared-request-evidence-0123456789abcdef")
            with sqlite3.connect(path) as db:
                payload = db.execute(
                    "SELECT payload_json FROM private_outcome_outbox WHERE outcome_id=?",
                    (outcome_id,),
                ).fetchone()[0]
            self.assertIn('"bandwidth_mbps":800.0', payload)
            self.assertIn('"verification_status":"verified"', payload)
            self.assertNotIn("ttft", payload.lower())

    def test_same_outcome_id_with_changed_payload_is_rejected(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            feedback = PrivateOutcomeFeedback(
                endpoint="https://control.example.test/internal/v1/outcomes",
                bearer_token="secret",
                outbox_path=Path(tmp) / "outbox.sqlite3",
            )
            verified = _verified()
            feedback.enqueue_verified_success(
                model_id="model-a",
                coordinator_node_id="node-a",
                worker_node_id="node-b",
                network_result=_network(),
                verified=verified,
            )
            changed = _network()
            changed["metrics"]["download_mbps_p50"] = 700.0
            with self.assertRaises(PrivateFeedbackError):
                feedback.enqueue_verified_success(
                    model_id="model-a",
                    coordinator_node_id="node-a",
                    worker_node_id="node-b",
                    network_result=changed,
                    verified=verified,
                )

    def test_execution_failure_is_queued_as_not_produced_not_invalid(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "outbox.sqlite3"
            feedback = PrivateOutcomeFeedback(
                endpoint="https://control.example.test/internal/v1/outcomes",
                bearer_token="secret",
                outbox_path=path,
            )
            outcome_id = feedback.enqueue_execution_failure(
                attempt_job_id="job-a1",
                decision_id="placement-0123456789abcdef",
                model_id="model-a",
                coordinator_node_id="node-a",
                worker_node_id="node-b",
                network_result=_network(),
                disconnected_node_ids=("node-b",),
            )
            with sqlite3.connect(path) as db:
                payload = db.execute(
                    "SELECT payload_json FROM private_outcome_outbox WHERE outcome_id=?",
                    (outcome_id,),
                ).fetchone()[0]
            self.assertIn('"verification_status":"not_produced"', payload)
            self.assertNotIn('"verification_status":"invalid"', payload)


if __name__ == "__main__":
    unittest.main()
