import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from runtime.llama.rpc_spike import (
    RpcEndpoint,
    RpcSpikeError,
    SpikePlan,
    SpikeResult,
    build_coordinator_command,
    build_discover_command,
    build_worker_command,
    compare_results,
    completion_payload,
    parse_completion_response,
    run_spike,
    sha256_file,
)


class RpcSpikeTests(unittest.TestCase):
    def endpoint(self):
        return RpcEndpoint.parse("192.168.1.20:50052")

    def plan(self):
        return SpikePlan(
            Path("llama-server"), Path("model.gguf"), (self.endpoint(),),
            ("CUDA0", "RPC0[192.168.1.20:50052]"), (3, 1)
        )

    def test_rpc_endpoint_rejects_public_dns_and_ipv6(self):
        for value in ("8.8.8.8:50052", "example.com:50052", "[::1]:50052"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RpcEndpoint.parse(value)
        self.assertEqual(RpcEndpoint.parse("127.0.0.1:50052").host, "127.0.0.1")
        self.assertEqual(RpcEndpoint.parse("10.2.3.4:50052").host, "10.2.3.4")

    def test_worker_command_never_adds_cache_or_public_bind(self):
        command = build_worker_command("ggml-rpc-server", bind="192.168.1.20", devices=("CUDA0",))
        self.assertEqual(command[:5], ["ggml-rpc-server", "--host", "192.168.1.20", "--port", "50052"])
        self.assertNotIn("--cache", command)
        with self.assertRaises(ValueError):
            build_worker_command("ggml-rpc-server", bind="0.0.0.0")

    def test_discover_is_offline_and_private(self):
        self.assertEqual(
            build_discover_command("llama-server", (self.endpoint(),)),
            ["llama-server", "--offline", "--rpc", "192.168.1.20:50052", "--list-devices"],
        )

    def test_shared_plan_requires_local_and_rpc_devices(self):
        with self.assertRaises(ValueError):
            SpikePlan(Path("s"), Path("m"), (self.endpoint(),), ("CUDA0",), (1,))
        with self.assertRaises(ValueError):
            SpikePlan(Path("s"), Path("m"), (self.endpoint(),), ("CUDA0", "CUDA1"), (1, 1))
        with self.assertRaises(ValueError):
            SpikePlan(Path("s"), Path("m"), (self.endpoint(),), ("CUDA0", "RPC0[x]"), (1,))

    def test_coordinator_command_is_loopback_explicit_and_cache_disabled(self):
        command = build_coordinator_command(self.plan())
        joined = " ".join(command)
        for expected in (
            "--host 127.0.0.1", "--rpc 192.168.1.20:50052",
            "--device CUDA0,RPC0[192.168.1.20:50052]", "--split-mode layer",
            "--tensor-split 3,1", "--fit off", "--cache-ram 0",
        ):
            self.assertIn(expected, joined)
        self.assertIn("--offline", command)
        self.assertNotIn("0.0.0.0", joined)
        self.assertNotIn("--override-tensor", command)

    def test_local_baseline_omits_rpc(self):
        plan = SpikePlan(Path("s"), Path("m"), (), ("CUDA0",), (1,), mode="local_baseline")
        command = build_coordinator_command(plan)
        self.assertNotIn("--rpc", command)
        self.assertEqual(command[command.index("--split-mode") + 1], "none")
        self.assertNotIn("--tensor-split", command)

    def test_completion_payload_is_deterministic_and_no_cache(self):
        payload = completion_payload("probe", n_predict=16, seed=7)
        self.assertEqual(payload["temperature"], 0.0)
        self.assertFalse(payload["cache_prompt"])
        self.assertFalse(payload["stream"])
        self.assertTrue(payload["return_tokens"])

    def test_completion_parser_is_bounded(self):
        doc = {"content": "READY", "tokens": [1, 2, 3], "timings": {
            "prompt_n": 10, "prompt_ms": 5.0, "prompt_per_second": 2000.0,
            "predicted_n": 3, "predicted_ms": 30.0, "predicted_per_second": 100.0,
            "extra": "not persisted"}}
        content, tokens, timings = parse_completion_response(doc)
        self.assertEqual((content, tokens), ("READY", [1, 2, 3]))
        self.assertNotIn("extra", timings)
        with self.assertRaises(RpcSpikeError):
            parse_completion_response({"content": "x", "timings": {}})

    def test_model_hash_is_correct(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.gguf"; path.write_bytes(b"abc" * 10000)
            self.assertEqual(sha256_file(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_failure_artifact_contains_no_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); server = root / "server"; model = root / "model.gguf"
            server.write_bytes(b"x"); model.write_bytes(b"model")
            plan = SpikePlan(server, model, (), ("CUDA0",), (1,), mode="local_baseline")
            with patch("runtime.llama.rpc_spike.runtime_version", side_effect=RpcSpikeError("bad version")):
                with self.assertRaises(RpcSpikeError):
                    run_spike(plan, prompt="SENSITIVE PROMPT", output_dir=root / "run")
            failure = json.loads((root / "run" / "runtime_spike_failure.json").read_text())
            self.assertEqual(failure["phase"], "runtime_version")
            self.assertNotIn("SENSITIVE PROMPT", json.dumps(failure))
            self.assertLessEqual(len(failure["message"]), 1024)

    def test_compare_requires_same_model_prompt_and_reports_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, shared = Path(tmp) / "base.json", Path(tmp) / "shared.json"
            common = {"model": {"sha256": "a" * 64},
                      "correctness": {"prompt_sha256": "b" * 64, "output_sha256": "c" * 64, "token_ids_sha256": "d" * 64},
                      "timings": {"prompt_per_second": 100.0, "predicted_per_second": 50.0, "request_ms": 1000.0}}
            base.write_text(json.dumps({**common, "placement": {"mode": "local_baseline"}}))
            remote = json.loads(json.dumps(common)); remote["placement"] = {"mode": "shared_rpc"}
            remote["timings"].update(prompt_per_second=80.0, predicted_per_second=40.0, request_ms=1200.0)
            shared.write_text(json.dumps(remote))
            result = compare_results(base, shared)
            self.assertTrue(result["exact_output_match"])
            self.assertEqual(result["match_basis"], "token_ids_sha256")
            self.assertAlmostEqual(result["shared_over_baseline"]["predicted_tokens_per_second"], 0.8)
            remote["model"]["sha256"] = "e" * 64; shared.write_text(json.dumps(remote))
            with self.assertRaises(RpcSpikeError):
                compare_results(base, shared)

    def test_result_schema_forbids_raw_prompt_and_output(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "spike_result.schema.json").read_text())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        result = SpikeResult(
            1, "llama-rpc-0123456789abcdef", "2026-08-21T19:00:00Z",
            {"name": "llama.cpp", "version": "build: 1"},
            {"basename": "model.gguf", "size_bytes": 123, "sha256": "a" * 64},
            {"rpc_endpoints": ["192.168.1.20:50052"], "coordinator_http": "127.0.0.1:18080"},
            {"mode": "shared_rpc", "split_mode": "layer", "devices": ["CUDA0", "RPC0[x]"], "tensor_split": [3.0, 1.0], "fit": False},
            {"model_ready_ms": 10.0, "request_ms": 20.0, "prompt_n": 5, "prompt_ms": 4.0,
             "prompt_per_second": 1250.0, "predicted_n": 2, "predicted_ms": 10.0, "predicted_per_second": 200.0},
            {"prompt_sha256": "b" * 64, "output_sha256": "c" * 64, "token_ids_sha256": "d" * 64},
        ).to_dict()
        validator.validate(result)
        local = json.loads(json.dumps(result)); local["placement"] = {"mode": "local_baseline", "split_mode": "none", "devices": ["CUDA0"], "tensor_split": [1.0], "fit": False}; local["topology"]["rpc_endpoints"] = []
        validator.validate(local)
        bad = dict(result); bad["raw_output"] = "secret"
        self.assertTrue(list(validator.iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
