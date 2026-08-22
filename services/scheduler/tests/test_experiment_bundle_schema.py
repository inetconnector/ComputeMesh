import copy
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

import test_evidence_bundle as fixtures

from services.scheduler.evidence_bundle import build_experiment_bundle, select_evidence


class ExperimentBundleSchemaTests(unittest.TestCase):
    def test_unknown_provenance_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coordinator = root / "coordinator"
            worker = root / "worker"
            manifest_path = root / "manifest.json"
            fixtures.write_json(coordinator / "node_profile.json", fixtures.profile("node-a"))
            fixtures.write_json(worker / "node_profile.json", fixtures.profile("node-b", gpu_memory=6_000_000_000))
            fixtures.write_json(coordinator / "cp.json", fixtures.bench("llama_cpp_prefill", "cp", tps=300.0))
            fixtures.write_json(coordinator / "cd.json", fixtures.bench("llama_cpp_decode", "cd", tps=80.0))
            fixtures.write_json(worker / "wp.json", fixtures.bench("llama_cpp_prefill", "wp", tps=120.0))
            fixtures.write_json(worker / "wd.json", fixtures.bench("llama_cpp_decode", "wd", tps=35.0))
            fixtures.write_json(
                coordinator / "net.json",
                fixtures.bench("tcp_network_path", "net", local="node-a", peer="node-b"),
            )
            fixtures.write_json(manifest_path, fixtures.manifest())
            bundle = build_experiment_bundle(
                select_evidence(
                    coordinator_root=coordinator,
                    worker_root=worker,
                    model_manifest=manifest_path,
                ),
                now=fixtures.NOW,
            )
            schema = json.loads(
                (Path(__file__).resolve().parents[1] / "experiment_bundle.schema.json").read_text(encoding="utf-8")
            )
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            validator.validate(bundle)
            invalid = copy.deepcopy(bundle)
            invalid["sources"]["coordinator"]["profile"]["absolute_path"] = "C:/secret/lab/node_profile.json"
            self.assertTrue(list(validator.iter_errors(invalid)))


if __name__ == "__main__":
    unittest.main()
