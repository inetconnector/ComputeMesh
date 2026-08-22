import tempfile
from pathlib import Path
import unittest

import test_evidence_bundle as fixtures

from services.scheduler.evidence_bundle import (
    EvidenceBundleError,
    build_experiment_bundle,
    select_evidence,
)


class EvidenceBundleLegacyBindingTests(unittest.TestCase):
    def test_embedded_caller_asserted_peer_binding_cannot_produce_current_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coordinator = root / "coordinator"
            worker = root / "worker"
            manifest_path = root / "manifest.json"
            fixtures.write_json(coordinator / "node_profile.json", fixtures.profile("node-a"))
            fixtures.write_json(worker / "node_profile.json", fixtures.profile("node-b", gpu_memory=6_000_000_000))
            fixtures.write_json(
                coordinator / "cp.json",
                fixtures.bench("llama_cpp_prefill", "cp", tps=300.0),
            )
            fixtures.write_json(
                coordinator / "cd.json",
                fixtures.bench("llama_cpp_decode", "cd", tps=80.0),
            )
            fixtures.write_json(
                worker / "wp.json",
                fixtures.bench("llama_cpp_prefill", "wp", tps=120.0),
            )
            fixtures.write_json(
                worker / "wd.json",
                fixtures.bench("llama_cpp_decode", "wd", tps=35.0),
            )
            network = fixtures.bench(
                "tcp_network_path",
                "net",
                local="node-a",
                peer="node-b",
            )
            network["conditions"]["peer_identity_binding"] = "caller_asserted_v1"
            fixtures.write_json(coordinator / "net.json", network)
            fixtures.write_json(manifest_path, fixtures.manifest())

            selected = select_evidence(
                coordinator_root=coordinator,
                worker_root=worker,
                model_manifest=manifest_path,
            )
            with self.assertRaisesRegex(EvidenceBundleError, "legacy network-peer fallback"):
                build_experiment_bundle(selected, now=fixtures.NOW)


if __name__ == "__main__":
    unittest.main()
