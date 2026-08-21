import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from services.scheduler.placement import PlacementInputError, PlannerPolicy, build_placement_decision

NOW = datetime(2026, 8, 21, 20, 30, tzinfo=timezone.utc)
MODEL_SIZE = 8_000_000_000
DIGEST = "sha256:" + "a" * 64


def profile(node_id, *, revision=3, memory=16_000_000_000, gpu_memory=10_000_000_000, captured="2026-08-21T20:00:00Z", draining=False):
    return {
        "schema_version": 1,
        "node_id": node_id,
        "profile_revision": revision,
        "captured_at": captured,
        "platform": {"os": "TestOS", "release": "1", "architecture": "x86_64", "python_version": "3.11"},
        "cpu": {"model": "Test CPU", "logical_cores": 8},
        "memory": {"total_bytes": memory, "available_bytes": memory},
        "devices": [] if gpu_memory == 0 else [{
            "device_id": "gpu:0", "kind": "gpu", "vendor": "Test", "name": "Test GPU",
            "memory_total_bytes": gpu_memory, "driver_version": "1", "backend": "cuda"
        }],
        "runtime_capabilities": [],
        "provider_limits": {"draining": draining, "max_memory_fraction": 0.90, "max_power_watts": None},
        "benchmark_refs": [],
    }


def manifest(size=MODEL_SIZE, *, partition=True):
    return {
        "schema_version": 1,
        "model_id": "test-model",
        "model_version": "1",
        "architecture": "test",
        "license": {"id": "test", "source": "test", "redistribution_allowed": False},
        "runtime_compatibility": [{"runtime": "llama.cpp"}],
        "quantizations": ["Q4_K_M"],
        "partitioning": {"allowed": ["contiguous_layers"] if partition else ["replica"]},
        "artifacts": [{"digest": DIGEST, "size_bytes": size, "media_type": "application/x-gguf"}],
    }


def bench(name, run_id, revision, model_name="model.gguf", size=MODEL_SIZE, tps=100.0):
    metrics = {
        "model_name": model_name,
        "model_size_bytes": size,
    }
    if name == "llama_cpp_prefill":
        metrics.update({"prefill_tokens_per_second_avg": tps, "prompt_tokens": 512})
    elif name == "llama_cpp_decode":
        metrics.update({"decode_tokens_per_second_avg": tps, "generated_tokens": 128})
    elif name == "tcp_network_path":
        metrics = {
            "rtt_ms_p50": 2.0,
            "rtt_ms_p95": 3.0,
            "upload_mbps_p50": 900.0,
            "download_mbps_p50": 850.0,
        }
    return {
        "schema_version": 1, "run_id": run_id, "benchmark_name": name,
        "captured_at": "2026-08-21T20:05:00Z", "profile_revision": revision,
        "conditions": {"warm_state": "warm"}, "metrics": metrics, "raw_samples": []
    }


def inputs():
    return dict(
        coordinator_profile=profile("node-a", gpu_memory=10_000_000_000),
        worker_profile=profile("node-b", gpu_memory=6_000_000_000),
        model_manifest=manifest(),
        coordinator_prefill=bench("llama_cpp_prefill", "cp", 3, tps=300.0),
        coordinator_decode=bench("llama_cpp_decode", "cd", 3, tps=80.0),
        worker_prefill=bench("llama_cpp_prefill", "wp", 3, tps=120.0),
        worker_decode=bench("llama_cpp_decode", "wd", 3, tps=35.0),
        network_result=bench("tcp_network_path", "net", 3),
        network_peer_node_id="node-b",
        layer_count=32,
        now=NOW,
    )


class PlacementTests(unittest.TestCase):
    def test_shared_candidate_is_contiguous_and_complete(self):
        decision = build_placement_decision(**inputs())
        self.assertEqual(decision["recommendation"]["mode"], "shared_experiment")
        shared = decision["candidates"][1]
        self.assertTrue(shared["feasible"])
        first, second = shared["layer_ranges"]
        self.assertEqual(first["start_layer"], 0)
        self.assertEqual(first["end_layer_exclusive"], second["start_layer"])
        self.assertEqual(second["end_layer_exclusive"], 32)
        self.assertEqual(len(shared["tensor_split"]), 2)

    def test_decision_id_is_deterministic_for_same_evidence(self):
        a = build_placement_decision(**inputs())
        b = build_placement_decision(**inputs())
        self.assertEqual(a["decision_id"], b["decision_id"])

    def test_does_not_claim_shared_speedup_without_shared_measurement(self):
        decision = build_placement_decision(**inputs())
        perf = decision["performance_evidence"]
        self.assertEqual(perf["status"], "insufficient_shared_runtime_evidence")
        self.assertIsNone(perf["predicted_shared_request_ms"])
        self.assertIsNone(perf["predicted_speedup_vs_local"])
        self.assertFalse(decision["recommendation"]["production_scheduling"])

    def test_worker_draining_blocks_shared_but_not_local_baseline(self):
        data = inputs()
        data["worker_profile"]["provider_limits"]["draining"] = True
        decision = build_placement_decision(**data)
        self.assertTrue(decision["candidates"][0]["feasible"])
        self.assertFalse(decision["candidates"][1]["feasible"])
        self.assertEqual(decision["recommendation"]["mode"], "local_only")

    def test_stale_coordinator_blocks_all_candidates(self):
        data = inputs()
        data["coordinator_profile"]["captured_at"] = "2026-08-19T20:00:00Z"
        decision = build_placement_decision(**data)
        self.assertFalse(decision["candidates"][0]["feasible"])
        self.assertFalse(decision["candidates"][1]["feasible"])
        self.assertEqual(decision["recommendation"]["mode"], "no_plan")

    def test_small_worker_memory_falls_back_to_local(self):
        data = inputs()
        data["worker_profile"] = profile("node-b", gpu_memory=200_000_000)
        decision = build_placement_decision(**data)
        self.assertTrue(decision["candidates"][0]["feasible"])
        self.assertFalse(decision["candidates"][1]["feasible"])
        self.assertEqual(decision["recommendation"]["mode"], "local_only")

    def test_no_memory_plan_is_explicit(self):
        data = inputs()
        data["coordinator_profile"] = profile("node-a", memory=2_000_000_000, gpu_memory=0)
        data["worker_profile"] = profile("node-b", memory=2_000_000_000, gpu_memory=0)
        decision = build_placement_decision(**data)
        self.assertEqual(decision["recommendation"]["mode"], "no_plan")

    def test_revision_mismatch_rejected(self):
        data = inputs()
        data["worker_decode"]["profile_revision"] = 2
        with self.assertRaisesRegex(PlacementInputError, "profile revision"):
            build_placement_decision(**data)

    def test_model_size_mismatch_rejected(self):
        data = inputs()
        data["worker_decode"]["metrics"]["model_size_bytes"] = MODEL_SIZE - 1
        with self.assertRaisesRegex(PlacementInputError, "model_size_bytes"):
            build_placement_decision(**data)

    def test_network_peer_binding_mismatch_rejected(self):
        data = inputs()
        data["network_peer_node_id"] = "node-c"
        with self.assertRaisesRegex(PlacementInputError, "network peer"):
            build_placement_decision(**data)

    def test_partitioning_must_allow_contiguous_layers(self):
        data = inputs()
        data["model_manifest"] = manifest(partition=False)
        with self.assertRaisesRegex(PlacementInputError, "contiguous_layers"):
            build_placement_decision(**data)

    def test_cpu_fallback_uses_available_system_memory(self):
        data = inputs()
        data["worker_profile"] = profile("node-b", memory=12_000_000_000, gpu_memory=0)
        decision = build_placement_decision(**data)
        self.assertEqual(decision["nodes"]["worker"]["kind"], "cpu")
        self.assertEqual(decision["nodes"]["worker"]["device_id"], "cpu:system-memory")

    def test_output_validates_against_decision_schema(self):
        decision = build_placement_decision(**inputs())
        schema = json.loads((Path(__file__).resolve().parents[1] / "placement_decision.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(decision)

    def test_policy_is_bounded(self):
        with self.assertRaises(ValueError):
            PlannerPolicy(planner_memory_fraction=1.1)
        with self.assertRaises(ValueError):
            PlannerPolicy(fixed_model_overhead_fraction=0.5)


if __name__ == "__main__":
    unittest.main()
