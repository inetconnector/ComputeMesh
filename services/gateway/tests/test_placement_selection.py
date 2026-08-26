from __future__ import annotations

import json
import tempfile
import unittest

from services.gateway.placement_selection import (
    PlacementSelectionError,
    load_shared_placement_selection,
)


DIGEST = "sha256:" + "a" * 64


def _decision(*, mode="shared_experiment", shared_feasible=True, hard_pass=True):
    return {
        "schema_version": 1,
        "decision_id": "placement-0123456789abcdef",
        "captured_at": "2026-08-26T08:00:00Z",
        "scope": "m1_two_node_llama_experiment",
        "model": {
            "model_id": "qwen-test",
            "model_version": "1",
            "artifact_digest": DIGEST,
            "artifact_size_bytes": 1000,
            "benchmark_model_name": "model.gguf",
            "layer_count": 10,
            "layer_count_source": "model_manifest_v1",
        },
        "nodes": {
            "coordinator": {
                "node_id": "node-a", "device_id": "gpu:0", "kind": "gpu",
                "name": "GPU A", "raw_memory_bytes": 10000,
                "provider_memory_fraction": 1.0, "planner_memory_fraction": 0.9,
                "effective_memory_fraction": 0.9, "usable_memory_bytes": 9000,
                "profile_revision": 1, "profile_age_hours": 0.1,
            },
            "worker": {
                "node_id": "node-b", "device_id": "gpu:0", "kind": "gpu",
                "name": "GPU B", "raw_memory_bytes": 10000,
                "provider_memory_fraction": 1.0, "planner_memory_fraction": 0.9,
                "effective_memory_fraction": 0.9, "usable_memory_bytes": 9000,
                "profile_revision": 1, "profile_age_hours": 0.1,
            },
        },
        "network_evidence": {
            "run_id": "net-1",
            "peer_node_id": "node-b",
            "peer_binding": "caller_asserted_v1",
        },
        "hard_constraints": [
            {"name": f"c{i}", "passed": hard_pass, "detail": "ok"}
            for i in range(5)
        ],
        "candidates": [
            {
                "mode": "local_only", "feasible": True,
                "layer_ranges": [{"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 10}],
                "tensor_split": [1.0], "explanation": "local",
            },
            {
                "mode": "shared_contiguous_layers", "feasible": shared_feasible,
                "layer_ranges": (
                    [
                        {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 4},
                        {"node_id": "node-b", "start_layer": 4, "end_layer_exclusive": 10},
                    ] if shared_feasible else []
                ),
                "tensor_split": ([4.0, 6.0] if shared_feasible else []),
                "memory_model": {
                    "fixed_coordinator_bytes": 100,
                    "estimated_layer_bytes": 90,
                    "coordinator_max_layers": 10,
                    "worker_max_layers": 10,
                },
                "explanation": "shared",
            },
        ],
        "performance_evidence": {
            "status": "insufficient_shared_runtime_evidence",
            "coordinator_prefill_tokens_per_second": 10.0,
            "coordinator_decode_tokens_per_second": 10.0,
            "worker_prefill_tokens_per_second": 10.0,
            "worker_decode_tokens_per_second": 10.0,
            "network_rtt_ms_p50": 1.0,
            "network_rtt_ms_p95": 2.0,
            "network_upload_mbps_p50": 100.0,
            "network_download_mbps_p50": 100.0,
            "predicted_shared_request_ms": None,
            "predicted_speedup_vs_local": None,
            "reason": "not measured",
        },
        "recommendation": {
            "mode": mode,
            "production_scheduling": False,
            "explanation": "experiment only",
        },
    }


class PlacementSelectionTests(unittest.TestCase):
    def _write(self, value):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(value, tmp)
        tmp.close()
        self.addCleanup(lambda: __import__("os").unlink(tmp.name))
        return tmp.name

    def test_extracts_nodes_only_with_explicit_experimental_opt_in(self):
        path = self._write(_decision())
        with self.assertRaisesRegex(PlacementSelectionError, "experimental"):
            load_shared_placement_selection(path)
        selected = load_shared_placement_selection(path, allow_experimental=True)
        self.assertEqual(selected.provider_node_ids, ("node-a", "node-b"))
        self.assertEqual(selected.model_id, "qwen-test")
        self.assertEqual(selected.layer_ranges[1], ("node-b", 4, 10))

    def test_rejects_failed_hard_constraint(self):
        path = self._write(_decision(hard_pass=False))
        with self.assertRaisesRegex(PlacementSelectionError, "hard constraints"):
            load_shared_placement_selection(path, allow_experimental=True)

    def test_rejects_non_shared_recommendation(self):
        path = self._write(_decision(mode="local_only", shared_feasible=False))
        with self.assertRaisesRegex(PlacementSelectionError, "did not recommend"):
            load_shared_placement_selection(path, allow_experimental=True)


if __name__ == "__main__":
    unittest.main()
