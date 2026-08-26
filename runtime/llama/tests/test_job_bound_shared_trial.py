from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.llama.job_bound_shared_trial import run_job_bound_shared_trial
from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.tests.test_job_attestation import _evidence


class JobBoundSharedTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.output = self.root / "run"
        self.output.mkdir()
        self.evidence = self.output / "shared_run_evidence.json"
        self.evidence.write_text(
            json.dumps(_evidence(datetime.now(timezone.utc))),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_emits_job_bound_attestation_request_and_manifest(self):
        with patch(
            "runtime.llama.job_bound_shared_trial.run_shared_trial",
            return_value=self.evidence,
        ) as runner:
            evidence_path, request_path = run_job_bound_shared_trial(
                job_id="job-physical-123",
                bundle_path=self.root / "bundle.json",
                llama_server=self.root / "llama-server",
                model_path=self.root / "model.gguf",
                worker_rpc=RpcEndpoint("10.0.0.2", 50052),
                output_dir=self.output,
            )
        self.assertEqual(evidence_path, self.evidence)
        request = json.loads(request_path.read_text())
        self.assertEqual(request["job_id"], "job-physical-123")
        self.assertEqual(request["expected_nodes"], ["node-a", "node-b"])
        manifest = json.loads((self.output / "job_bound_shared_trial.json").read_text())
        self.assertFalse(manifest["settlement_ready"])
        self.assertEqual(manifest["job_id"], "job-physical-123")
        runner.assert_called_once()

    def test_invalid_job_id_fails_before_physical_run(self):
        with patch("runtime.llama.job_bound_shared_trial.run_shared_trial") as runner:
            with self.assertRaisesRegex(ValueError, "job_id"):
                run_job_bound_shared_trial(
                    job_id="",
                    bundle_path=self.root / "bundle.json",
                    llama_server=self.root / "llama-server",
                    model_path=self.root / "model.gguf",
                    worker_rpc=RpcEndpoint("10.0.0.2", 50052),
                    output_dir=self.output,
                )
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
