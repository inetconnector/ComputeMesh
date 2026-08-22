import json
from pathlib import Path
import tempfile
import unittest

from runtime.llama.shared_run_evidence import (
    SharedRunEvidenceError,
    build_shared_run_evidence,
    write_shared_run_evidence,
)


MODEL_SHA = "a" * 64
PROMPT_SHA = "b" * 64
OUTPUT_SHA = "c" * 64
TOKEN_SHA = "d" * 64
SOURCE_SHA = "sha256:" + "e" * 64


def node(node_id: str) -> dict:
    return {
        "node_id": node_id,
        "device_id": "gpu0",
        "kind": "gpu",
        "name": "CUDA0",
        "raw_memory_bytes": 16_000_000_000,
        "provider_memory_fraction": 1.0,
        "planner_memory_fraction": 0.85,
        "effective_memory_fraction": 0.85,
        "usable_memory_bytes": 13_600_000_000,
        "profile_revision": 2,
        "profile_age_hours": 0.1,
    }


def source_profile(node_id: str) -> dict:
    return {
        "file_name": "profile.json",
        "document_sha256": SOURCE_SHA,
        "node_id": node_id,
        "profile_revision": 2,
    }


def source_bench(file_name: str, run_id: str) -> dict:
    return {"file_name": file_name, "document_sha256": SOURCE_SHA, "run_id": run_id}


def bundle() -> dict:
    placement = {
        "schema_version": 1,
        "decision_id": "placement-0123456789abcdef",
        "captured_at": "2026-08-22T05:30:00Z",
        "scope": "m1_two_node_llama_experiment",
        "model": {
            "model_id": "model-a",
            "model_version": "1",
            "artifact_digest": "sha256:" + MODEL_SHA,
            "artifact_size_bytes": 1234,
            "benchmark_model_name": "model.gguf",
            "layer_count": 40,
            "layer_count_source": "model_manifest_v1",
        },
        "nodes": {"coordinator": node("node-a"), "worker": node("node-b")},
        "network_evidence": {
            "run_id": "net-1",
            "peer_node_id": "node-b",
            "peer_binding": "unauthenticated_server_report_v1",
        },
        "hard_constraints": [
            {"name": f"c{i}", "passed": True, "detail": "ok"} for i in range(5)
        ],
        "candidates": [
            {
                "mode": "local_only",
                "feasible": True,
                "layer_ranges": [
                    {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 40}
                ],
                "tensor_split": [1.0],
                "explanation": "local fits",
            },
            {
                "mode": "shared_contiguous_layers",
                "feasible": True,
                "layer_ranges": [
                    {"node_id": "node-a", "start_layer": 0, "end_layer_exclusive": 30},
                    {"node_id": "node-b", "start_layer": 30, "end_layer_exclusive": 40},
                ],
                "tensor_split": [30.0, 10.0],
                "memory_model": {
                    "fixed_coordinator_bytes": 124,
                    "estimated_layer_bytes": 28,
                    "coordinator_max_layers": 40,
                    "worker_max_layers": 20,
                },
                "explanation": "shared fits",
            },
        ],
        "performance_evidence": {
            "status": "insufficient_shared_runtime_evidence",
            "coordinator_prefill_tokens_per_second": 300.0,
            "coordinator_decode_tokens_per_second": 80.0,
            "worker_prefill_tokens_per_second": 120.0,
            "worker_decode_tokens_per_second": 35.0,
            "network_rtt_ms_p50": 1.0,
            "network_rtt_ms_p95": 2.0,
            "network_upload_mbps_p50": 900.0,
            "network_download_mbps_p50": 900.0,
            "predicted_shared_request_ms": None,
            "predicted_speedup_vs_local": None,
            "reason": "not yet measured",
        },
        "recommendation": {
            "mode": "shared_experiment",
            "production_scheduling": False,
            "explanation": "run controlled experiment",
        },
    }
    return {
        "schema_version": 1,
        "bundle_id": "experiment-bundle-0123456789abcdef",
        "captured_at": "2026-08-22T05:30:00Z",
        "scope": "m1_two_node_placement_evidence",
        "benchmark_model_name": "model.gguf",
        "runtime_build": {
            "runtime": "llama.cpp",
            "llama_build_commit": "abcdef0",
            "llama_build_number": 999,
            "binding": "selected_llama_bench_v1",
        },
        "sources": {
            "model_manifest": {
                "file_name": "manifest.json",
                "document_sha256": SOURCE_SHA,
                "model_id": "model-a",
                "model_version": "1",
                "artifact_digest": "sha256:" + MODEL_SHA,
                "artifact_size_bytes": 1234,
                "layer_count": 40,
            },
            "coordinator": {
                "profile": source_profile("node-a"),
                "prefill": source_bench("cp.json", "cp"),
                "decode": source_bench("cd.json", "cd"),
            },
            "worker": {
                "profile": source_profile("node-b"),
                "prefill": source_bench("wp.json", "wp"),
                "decode": source_bench("wd.json", "wd"),
            },
            "network": {
                "file_name": "net.json",
                "document_sha256": SOURCE_SHA,
                "run_id": "net-1",
                "local_node_id": "node-a",
                "peer_node_id": "node-b",
                "peer_identity_binding": "unauthenticated_server_report_v1",
            },
        },
        "placement_decision": placement,
    }


def spike(mode: str) -> dict:
    shared = mode == "shared_rpc"
    return {
        "schema_version": 1,
        "run_id": "llama-rpc-1111111111111111" if shared else "llama-rpc-0000000000000000",
        "captured_at": "2026-08-22T05:31:00Z" if shared else "2026-08-22T05:30:10Z",
        "runtime": {"name": "llama.cpp", "version": "version: 999 (`abcdef0`)\nbuilt with test"},
        "model": {"basename": "model.gguf", "size_bytes": 1234, "sha256": MODEL_SHA},
        "topology": {
            "rpc_endpoints": ["127.0.0.1:50053"] if shared else [],
            "coordinator_http": "127.0.0.1:18080",
        },
        "placement": {
            "mode": mode,
            "split_mode": "layer" if shared else "none",
            "devices": ["CUDA0", "RPC0[127.0.0.1:50053]"] if shared else ["CUDA0"],
            "tensor_split": [30.0, 10.0] if shared else [1.0],
            "fit": False,
        },
        "timings": {
            "model_ready_ms": 10.0,
            "request_ms": 120.0 if shared else 100.0,
            "prompt_n": 16,
            "prompt_ms": 10.0,
            "prompt_per_second": 1200.0 if shared else 1400.0,
            "predicted_n": 4,
            "predicted_ms": 40.0,
            "predicted_per_second": 90.0 if shared else 100.0,
        },
        "correctness": {
            "prompt_sha256": PROMPT_SHA,
            "output_sha256": OUTPUT_SHA,
            "token_ids_sha256": TOKEN_SHA,
        },
    }


def relay() -> dict:
    return {
        "schema_version": 1,
        "started_at": "2026-08-22T05:30:30Z",
        "connected_at": "2026-08-22T05:30:40Z",
        "ended_at": "2026-08-22T05:31:10Z",
        "listen": "127.0.0.1:50053",
        "target": "192.168.1.20:50052",
        "setup_elapsed_ms": 10000.0,
        "active_elapsed_ms": 30000.0,
        "total_elapsed_ms": 40000.0,
        "configured": {
            "one_way_delay_ms": 0.0,
            "jitter_ms": 0.0,
            "seed": 1,
            "chunk_bytes": 65536,
            "max_buffer_bytes": 1048576,
            "disconnect_after_bytes": None,
            "disconnect_after_seconds": None,
            "connect_timeout_seconds": 10.0,
        },
        "traffic": {
            "coordinator_to_worker_bytes": 1000,
            "worker_to_coordinator_bytes": 2000,
            "total_forwarded_bytes": 3000,
        },
        "termination": {"reason": "eof", "error_type": None, "message": None},
    }


class SharedRunEvidenceTests(unittest.TestCase):
    def write_inputs(self, root: Path, *, b=None, base=None, shared=None, relay_doc=None):
        docs = {
            "bundle.json": b if b is not None else bundle(),
            "baseline.json": base if base is not None else spike("local_baseline"),
            "shared.json": shared if shared is not None else spike("shared_rpc"),
            "relay.json": relay_doc if relay_doc is not None else relay(),
        }
        for name, value in docs.items():
            (root / name).write_text(json.dumps(value), encoding="utf-8")
        return tuple(root / name for name in docs)

    def build(self, root: Path, **kwargs):
        paths = self.write_inputs(root, **kwargs)
        return build_shared_run_evidence(
            bundle_path=paths[0], baseline_path=paths[1], shared_path=paths[2], relay_path=paths[3]
        )

    def assert_rejected(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SharedRunEvidenceError):
            self.build(Path(tmp), **kwargs)

    def test_builds_bound_shared_runtime_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.build(Path(tmp))
        self.assertEqual(result["scope"], "m1_two_node_shared_runtime_proof")
        self.assertTrue(result["correctness"]["exact_output_match"])
        self.assertEqual(result["correctness"]["match_basis"], "token_ids_sha256")
        self.assertEqual(result["planner_split"]["tensor_split"], [30.0, 10.0])
        self.assertEqual(result["performance"]["total_forwarded_bytes"], 3000)
        self.assertFalse(result["production_scheduling"])
        self.assertNotIn("raw", json.dumps(result).lower())

    def test_rejects_bundle_without_shared_recommendation(self):
        value = bundle(); value["placement_decision"]["recommendation"]["mode"] = "local_only"
        self.assert_rejected(b=value)

    def test_rejects_model_or_runtime_mismatch(self):
        for mutation in ("model", "runtime"):
            value = spike("shared_rpc")
            if mutation == "model": value["model"]["sha256"] = "f" * 64
            else: value["runtime"]["version"] = "different build"
            with self.subTest(mutation=mutation): self.assert_rejected(shared=value)

    def test_rejects_split_or_device_order_not_selected_by_planner(self):
        split = spike("shared_rpc"); split["placement"]["tensor_split"] = [20.0, 20.0]
        self.assert_rejected(shared=split)
        order = spike("shared_rpc"); order["placement"]["devices"] = list(reversed(order["placement"]["devices"]))
        self.assert_rejected(shared=order)
        local = spike("shared_rpc"); local["placement"]["devices"][0] = "CUDA1"
        self.assert_rejected(shared=local)

    def test_rejects_shared_run_that_bypasses_relay_or_public_target(self):
        value = spike("shared_rpc"); value["topology"]["rpc_endpoints"] = ["192.168.1.20:50052"]
        self.assert_rejected(shared=value)
        metrics = relay(); metrics["target"] = "8.8.8.8:50052"
        self.assert_rejected(relay_doc=metrics)

    def test_rejects_perturbed_or_forced_disconnect_relay_for_first_proof(self):
        delay = relay(); delay["configured"]["one_way_delay_ms"] = 5.0
        self.assert_rejected(relay_doc=delay)
        disconnect = relay(); disconnect["configured"]["disconnect_after_bytes"] = 10
        self.assert_rejected(relay_doc=disconnect)

    def test_rejects_non_bidirectional_or_inconsistent_relay_bytes(self):
        zero = relay(); zero["traffic"]["worker_to_coordinator_bytes"] = 0; zero["traffic"]["total_forwarded_bytes"] = 1000
        self.assert_rejected(relay_doc=zero)
        bad_sum = relay(); bad_sum["traffic"]["total_forwarded_bytes"] = 9999
        self.assert_rejected(relay_doc=bad_sum)

    def test_rejects_incorrect_shared_output(self):
        value = spike("shared_rpc"); value["correctness"]["token_ids_sha256"] = "e" * 64
        self.assert_rejected(shared=value)

    def test_allows_output_digest_fallback_when_token_ids_are_absent(self):
        base, shared = spike("local_baseline"), spike("shared_rpc")
        base["correctness"]["token_ids_sha256"] = None; shared["correctness"]["token_ids_sha256"] = None
        with tempfile.TemporaryDirectory() as tmp:
            result = self.build(Path(tmp), base=base, shared=shared)
        self.assertEqual(result["correctness"]["match_basis"], "output_sha256")

    def test_rejects_stale_or_misordered_proof_timestamps(self):
        before_bundle = spike("local_baseline"); before_bundle["captured_at"] = "2026-08-22T05:29:59Z"
        self.assert_rejected(base=before_bundle)
        late = spike("shared_rpc"); late["captured_at"] = "2026-08-22T07:00:00Z"
        self.assert_rejected(shared=late)
        bad_relay = relay(); bad_relay["connected_at"] = "2026-08-22T05:30:20Z"
        self.assert_rejected(relay_doc=bad_relay)

    def test_rejects_non_finite_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); paths = self.write_inputs(root)
            paths[2].write_text(paths[2].read_text().replace("120.0", "NaN", 1), encoding="utf-8")
            with self.assertRaises(SharedRunEvidenceError):
                build_shared_run_evidence(
                    bundle_path=paths[0], baseline_path=paths[1], shared_path=paths[2], relay_path=paths[3]
                )

    def test_write_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); paths = self.write_inputs(root); output = root / "proof.json"
            kwargs = dict(bundle_path=paths[0], baseline_path=paths[1], shared_path=paths[2], relay_path=paths[3], output_path=output)
            write_shared_run_evidence(**kwargs)
            with self.assertRaises(SharedRunEvidenceError): write_shared_run_evidence(**kwargs)

    def test_symlink_input_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); paths = self.write_inputs(root); link = root / "bundle-link.json"
            try: link.symlink_to(paths[0].name)
            except (OSError, NotImplementedError): self.skipTest("symlink creation unavailable")
            with self.assertRaises(SharedRunEvidenceError):
                build_shared_run_evidence(bundle_path=link, baseline_path=paths[1], shared_path=paths[2], relay_path=paths[3])


if __name__ == "__main__":
    unittest.main()
