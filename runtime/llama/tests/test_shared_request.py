from __future__ import annotations

from types import SimpleNamespace
import unittest

from runtime.llama.shared_request import SharedRequestError, build_shared_request_evidence


class SharedRequestEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.plan = SimpleNamespace(
            placement_decision_id="placement-0123456789abcdef",
            model_basename="model.gguf",
            model_size_bytes=1234,
            model_sha256="a" * 64,
            tensor_split=(12.0, 20.0),
            layer_ranges=(
                {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 12},
                {"node_id": "node-b", "start_layer": 12, "end_layer_exclusive": 32},
            ),
            coordinator_node_id="node-a",
            worker_node_id="node-b",
        )

    def test_evidence_binds_actual_output_and_usage(self):
        evidence = build_shared_request_evidence(
            job_id="job-123",
            plan=self.plan,
            runtime_version_text="llama.cpp build 123",
            prompt="hello",
            content="world",
            timings={"prompt_n": 4, "predicted_n": 2, "request_ms": 12.5},
            relay_metrics={"client_to_target_bytes": 100, "target_to_client_bytes": 200},
        )
        self.assertEqual(evidence["job_id"], "job-123")
        self.assertEqual(evidence["participants"], ["node-a", "node-b"])
        self.assertEqual(evidence["request"]["prompt_tokens"], 4)
        self.assertEqual(evidence["request"]["completion_tokens"], 2)
        self.assertEqual(evidence["network"]["coordinator_to_worker_bytes"], 100)
        self.assertTrue(evidence["evidence_id"].startswith("shared-request-evidence-"))
        self.assertFalse(evidence["production_scheduling"])

    def test_missing_usage_is_rejected(self):
        with self.assertRaisesRegex(SharedRequestError, "timings"):
            build_shared_request_evidence(
                job_id="job-123",
                plan=self.plan,
                runtime_version_text="llama.cpp build 123",
                prompt="hello",
                content="world",
                timings={"prompt_n": 4},
                relay_metrics={"client_to_target_bytes": 100, "target_to_client_bytes": 200},
            )


if __name__ == "__main__":
    unittest.main()
