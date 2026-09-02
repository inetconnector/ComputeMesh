import importlib.util
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("cm_llama_bench_adapter", ROOT / "llama_bench_adapter.py")
adapter = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


class LlamaBenchAdapterTests(unittest.TestCase):
    def setUp(self):
        self.sample_text = Path(__file__).with_name("llama_bench_sample.json").read_text(encoding="utf-8")
        self.rows = adapter.parse_llama_bench_output(self.sample_text)

    def test_parse_json_and_jsonl(self):
        self.assertEqual(len(self.rows), 2)
        jsonl = "\n".join(json.dumps(row) for row in self.rows)
        self.assertEqual(len(adapter.parse_llama_bench_output(jsonl)), 2)

    def test_build_command(self):
        command = adapter.build_command(
            "llama-bench", "model.gguf", prompt_tokens=512, generated_tokens=128, repetitions=5
        )
        self.assertEqual(command[:3], ["llama-bench", "-m", "model.gguf"])
        self.assertEqual(command[-2:], ["-o", "json"])

    def test_build_command_binds_any_safe_gpu_device_and_full_offload(self):
        for device in ("CUDA0", "ROCm0", "HIP0", "Vulkan0"):
            command = adapter.build_command(
                "llama-bench",
                "model.gguf",
                prompt_tokens=512,
                generated_tokens=128,
                repetitions=5,
                device=device,
            )
            self.assertIn("--device", command)
            self.assertEqual(command[command.index("--device") + 1], device)
            self.assertIn("--n-gpu-layers", command)
            self.assertEqual(command[command.index("--n-gpu-layers") + 1], "all")

    def test_gpu_device_rejects_cpu_rpc_and_unsafe_values(self):
        for device in ("CPU", "RPC0", "none", "Vulkan 0", "CUDA0;rm"):
            with self.assertRaises(ValueError):
                adapter.build_command(
                    "llama-bench",
                    "model.gguf",
                    prompt_tokens=512,
                    generated_tokens=128,
                    repetitions=5,
                    device=device,
                )

    def test_convert_prefill_decode(self):
        results = adapter.convert_rows(self.rows, profile_revision=3, captured_at="2026-08-21T09:00:00Z")
        self.assertEqual([r["benchmark_name"] for r in results], ["llama_cpp_prefill", "llama_cpp_decode"])
        prefill, decode = results
        self.assertEqual(prefill["metrics"]["prefill_elapsed_ms_avg"], 100.0)
        self.assertEqual(prefill["metrics"]["prefill_tokens_per_second_avg"], 5120.0)
        self.assertEqual(decode["metrics"]["inter_token_ms_avg"], 7.8125)
        self.assertEqual(decode["metrics"]["model_name"], "example.Q4_K_M.gguf")

    def test_generated_results_validate_against_benchmark_schema(self):
        schema = json.loads((REPO / "protocol" / "schemas" / "benchmark_result.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for result in adapter.convert_rows(self.rows, profile_revision=0):
            validator.validate(result)

    def test_missing_phase_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            adapter.convert_rows([self.rows[0]], profile_revision=0)

    def test_bad_metrics_rejected(self):
        rows = [dict(row) for row in self.rows]
        rows[1]["avg_ts"] = 0
        with self.assertRaisesRegex(ValueError, "positive avg_ts"):
            adapter.convert_rows(rows, profile_revision=0)


if __name__ == "__main__":
    unittest.main()
