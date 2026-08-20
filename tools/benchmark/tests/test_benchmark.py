import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "benchmark.py"
spec = importlib.util.spec_from_file_location("cm_benchmark", MODULE_PATH)
benchmark = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(benchmark)


class BenchmarkHarnessTests(unittest.TestCase):
    def test_parse_nvidia_smi(self):
        devices = benchmark.parse_nvidia_smi("NVIDIA RTX 4090, 24564, 555.42\n")
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "gpu:0")
        self.assertEqual(devices[0]["vendor"], "NVIDIA")
        self.assertGreater(devices[0]["memory_total_bytes"], 24_000_000_000)

    def test_profile_and_result_contract(self):
        profile = benchmark.collect_node_profile("test-node", 3)
        result = benchmark.collect_inventory_benchmark(3, 1.25)
        profile["benchmark_refs"] = [result["run_id"]]
        benchmark.validate_semantic_minimum(profile, result)
        self.assertEqual(profile["profile_revision"], 3)
        self.assertEqual(result["profile_revision"], 3)
        self.assertGreaterEqual(profile["memory"]["total_bytes"], 0)

    def test_main_writes_parseable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = benchmark.main(["--node-id", "test-node", "--output-dir", tmp])
            self.assertEqual(rc, 0)
            profile = json.loads((Path(tmp) / "node_profile.json").read_text(encoding="utf-8"))
            result_files = list(Path(tmp).glob("benchmark_*.json"))
            self.assertEqual(len(result_files), 1)
            result = json.loads(result_files[0].read_text(encoding="utf-8"))
            benchmark.validate_semantic_minimum(profile, result)


if __name__ == "__main__":
    unittest.main()
