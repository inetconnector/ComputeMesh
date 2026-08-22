import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from services.scheduler.evidence_bundle import (
    EvidenceBundleError,
    build_experiment_bundle,
    select_evidence,
)

NOW = datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)
MODEL_SIZE = 8_000_000_000
DIGEST = "sha256:" + "b" * 64


def profile(node_id, revision=3, *, captured="2026-08-22T03:00:00Z", gpu_memory=10_000_000_000):
    return {
        "schema_version": 1,
        "node_id": node_id,
        "profile_revision": revision,
        "captured_at": captured,
        "platform": {
            "os": "TestOS",
            "release": "1",
            "architecture": "x86_64",
            "python_version": "3.11",
        },
        "cpu": {"model": "Test CPU", "logical_cores": 8},
        "memory": {"total_bytes": 16_000_000_000, "available_bytes": 15_000_000_000},
        "devices": [{
            "device_id": "gpu:0",
            "kind": "gpu",
            "vendor": "Test",
            "name": "Test GPU",
            "memory_total_bytes": gpu_memory,
            "driver_version": "1",
            "backend": "cuda",
        }],
        "runtime_capabilities": [],
        "provider_limits": {
            "draining": False,
            "max_memory_fraction": 0.90,
            "max_power_watts": None,
        },
        "benchmark_refs": [],
    }


def manifest(*, layer_count=32, size=MODEL_SIZE):
    value = {
        "schema_version": 1,
        "model_id": "test-model",
        "model_version": "1",
        "architecture": "test",
        "license": {"id": "test", "source": "test", "redistribution_allowed": False},
        "runtime_compatibility": [{"runtime": "llama.cpp"}],
        "quantizations": ["Q4_K_M"],
        "partitioning": {"allowed": ["contiguous_layers"]},
        "artifacts": [{
            "digest": DIGEST,
            "size_bytes": size,
            "media_type": "application/x-gguf",
        }],
    }
    if layer_count is not None:
        value["layer_count"] = layer_count
    return value


def bench(name, run_id, revision=3, *, captured="2026-08-22T03:10:00Z", model_name="model.gguf", size=MODEL_SIZE, tps=100.0, local=None, peer=None):
    if name == "llama_cpp_prefill":
        metrics = {
            "model_name": model_name,
            "model_size_bytes": size,
            "prefill_tokens_per_second_avg": tps,
            "prompt_tokens": 512,
        }
    elif name == "llama_cpp_decode":
        metrics = {
            "model_name": model_name,
            "model_size_bytes": size,
            "decode_tokens_per_second_avg": tps,
            "generated_tokens": 128,
        }
    elif name == "tcp_network_path":
        metrics = {
            "rtt_ms_p50": 2.0,
            "rtt_ms_p95": 3.0,
            "upload_mbps_p50": 900.0,
            "download_mbps_p50": 850.0,
        }
    else:
        raise ValueError(name)
    conditions = {"warm_state": "warm"}
    if local is not None:
        conditions["local_node_id"] = local
    if peer is not None:
        conditions["peer_node_id"] = peer
        conditions["peer_identity_binding"] = "unauthenticated_server_report_v1"
    return {
        "schema_version": 1,
        "run_id": run_id,
        "benchmark_name": name,
        "captured_at": captured,
        "profile_revision": revision,
        "conditions": conditions,
        "metrics": metrics,
        "raw_samples": [],
    }


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class EvidenceBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.coord = self.root / "coordinator-export"
        self.worker = self.root / "worker-export"
        self.manifest_path = self.root / "model.computemesh-model-manifest.json"
        write_json(self.coord / "inventory" / "node_profile.json", profile("node-a"))
        write_json(self.worker / "inventory" / "node_profile.json", profile("node-b", gpu_memory=6_000_000_000))
        write_json(self.coord / "llama" / "benchmark-cp.json", bench("llama_cpp_prefill", "cp", tps=300.0))
        write_json(self.coord / "llama" / "benchmark-cd.json", bench("llama_cpp_decode", "cd", tps=80.0))
        write_json(self.worker / "llama" / "benchmark-wp.json", bench("llama_cpp_prefill", "wp", tps=120.0))
        write_json(self.worker / "llama" / "benchmark-wd.json", bench("llama_cpp_decode", "wd", tps=35.0))
        write_json(
            self.coord / "network" / "benchmark-net.json",
            bench("tcp_network_path", "net", local="node-a", peer="node-b"),
        )
        write_json(self.manifest_path, manifest())

    def tearDown(self):
        self.tmp.cleanup()

    def select(self, **kwargs):
        return select_evidence(
            coordinator_root=self.coord,
            worker_root=self.worker,
            model_manifest=self.manifest_path,
            **kwargs,
        )

    def test_happy_path_builds_schema_valid_path_free_bundle(self):
        selected = self.select()
        bundle = build_experiment_bundle(selected, now=NOW)
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "experiment_bundle.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(bundle)
        self.assertEqual(bundle["benchmark_model_name"], "model.gguf")
        self.assertEqual(bundle["placement_decision"]["model"]["layer_count_source"], "model_manifest_v1")
        self.assertEqual(
            bundle["placement_decision"]["network_evidence"]["peer_binding"],
            "unauthenticated_server_report_v1",
        )
        serialized = json.dumps(bundle, sort_keys=True)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("coordinator-export", serialized)
        self.assertRegex(
            bundle["sources"]["coordinator"]["profile"]["document_sha256"],
            r"^sha256:[a-f0-9]{64}$",
        )

    def test_bundle_id_is_deterministic_for_same_sources(self):
        first = build_experiment_bundle(self.select(), now=NOW)
        second = build_experiment_bundle(self.select(), now=NOW)
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        self.assertEqual(
            first["placement_decision"]["decision_id"],
            second["placement_decision"]["decision_id"],
        )

    def test_current_bundle_rejects_manifest_without_layer_count(self):
        write_json(self.manifest_path, manifest(layer_count=None))
        with self.assertRaisesRegex(EvidenceBundleError, "requires model_manifest.layer_count"):
            self.select()

    def test_legacy_or_wrong_direction_network_is_not_eligible(self):
        write_json(
            self.coord / "network" / "benchmark-net.json",
            bench("tcp_network_path", "net", local=None, peer=None),
        )
        with self.assertRaisesRegex(EvidenceBundleError, "no matching coordinator"):
            self.select()
        write_json(
            self.coord / "network" / "benchmark-net.json",
            bench("tcp_network_path", "net", local="node-b", peer="node-a"),
        )
        with self.assertRaisesRegex(EvidenceBundleError, "no matching coordinator"):
            self.select()

    def test_highest_profile_revision_is_selected_and_old_benchmarks_are_ignored(self):
        write_json(self.coord / "old" / "node_profile.json", profile("node-a", revision=2, captured="2026-08-22T01:00:00Z"))
        write_json(self.coord / "old" / "benchmark-old-p.json", bench("llama_cpp_prefill", "old-p", revision=2, captured="2026-08-22T01:10:00Z"))
        write_json(self.coord / "old" / "benchmark-old-d.json", bench("llama_cpp_decode", "old-d", revision=2, captured="2026-08-22T01:10:00Z"))
        selected = self.select()
        self.assertEqual(selected.coordinator.profile.value["profile_revision"], 3)
        self.assertEqual(selected.coordinator.prefill.value["run_id"], "cp")

    def test_multiple_node_ids_fail_without_explicit_disambiguation(self):
        write_json(self.coord / "other" / "node_profile.json", profile("node-x", revision=4))
        with self.assertRaisesRegex(EvidenceBundleError, "multiple node IDs"):
            self.select()
        with self.assertRaisesRegex(EvidenceBundleError, "no common model basename"):
            self.select(coordinator_node_id="node-x")

    def test_multiple_common_model_names_require_explicit_choice(self):
        for role_root, prefix in ((self.coord, "c"), (self.worker, "w")):
            write_json(
                role_root / "llama2" / f"benchmark-{prefix}p2.json",
                bench("llama_cpp_prefill", f"{prefix}p2", model_name="other.gguf"),
            )
            write_json(
                role_root / "llama2" / f"benchmark-{prefix}d2.json",
                bench("llama_cpp_decode", f"{prefix}d2", model_name="other.gguf"),
            )
        with self.assertRaisesRegex(EvidenceBundleError, "multiple common model basenames"):
            self.select()
        selected = self.select(benchmark_model_name="model.gguf")
        self.assertEqual(selected.benchmark_model_name, "model.gguf")

    def test_equally_recent_distinct_benchmarks_are_ambiguous(self):
        write_json(
            self.coord / "llama" / "benchmark-cp-duplicate.json",
            bench("llama_cpp_prefill", "cp-2", captured="2026-08-22T03:10:00Z", tps=301.0),
        )
        with self.assertRaisesRegex(EvidenceBundleError, "ambiguous equally recent coordinator prefill"):
            self.select()

    def test_newer_unique_benchmark_is_selected(self):
        write_json(
            self.coord / "llama" / "benchmark-cp-new.json",
            bench("llama_cpp_prefill", "cp-new", captured="2026-08-22T03:20:00Z", tps=320.0),
        )
        selected = self.select()
        self.assertEqual(selected.coordinator.prefill.value["run_id"], "cp-new")

    def test_benchmark_before_profile_capture_is_not_eligible(self):
        write_json(
            self.worker / "llama" / "benchmark-wp.json",
            bench("llama_cpp_prefill", "wp", captured="2026-08-22T02:59:59Z"),
        )
        with self.assertRaisesRegex(EvidenceBundleError, "no common model basename"):
            self.select()

    def test_model_size_mismatch_is_not_silently_selected(self):
        write_json(
            self.worker / "llama" / "benchmark-wd.json",
            bench("llama_cpp_decode", "wd", size=MODEL_SIZE - 1),
        )
        with self.assertRaisesRegex(EvidenceBundleError, "no common model basename"):
            self.select()

    def test_evidence_looking_corrupt_document_fails_closed(self):
        invalid = profile("node-a", revision=4)
        invalid["memory"]["available_bytes"] = -1
        write_json(self.coord / "corrupt" / "node_profile.json", invalid)
        with self.assertRaisesRegex(EvidenceBundleError, "node profile.*invalid"):
            self.select()

    def test_requested_network_run_must_be_current_bound_direction(self):
        write_json(
            self.coord / "network" / "benchmark-net-new.json",
            bench(
                "tcp_network_path",
                "net-new",
                captured="2026-08-22T03:20:00Z",
                local="node-a",
                peer="node-b",
            ),
        )
        selected = self.select(network_run_id="net")
        self.assertEqual(selected.network.value["run_id"], "net")
        with self.assertRaisesRegex(EvidenceBundleError, "absent or does not bind"):
            self.select(network_run_id="missing")


if __name__ == "__main__":
    unittest.main()
