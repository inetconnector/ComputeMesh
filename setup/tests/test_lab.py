import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from setup import lab


class FakeRunner:
    def __init__(self, fail=False):
        self.commands = []
        self.fail = fail

    def __call__(self, command, cwd=None, check=None):
        self.commands.append((list(command), Path(cwd), check))
        if self.fail:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)


class LabSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "config.json"
        self.output_root = self.root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_config_uses_non_host_identifying_lab_id(self):
        cfg = lab.load_config(self.config_path)
        self.assertRegex(cfg.node_id, r"^lab-[0-9a-f]{8}$")
        self.assertEqual(cfg.profile_revision, 0)

    def test_inventory_revision_advances_only_after_success(self):
        cfg = lab.LabConfig(node_id="lab-12345678")
        runner = FakeRunner()
        with patch.object(lab, "REPO_ROOT", self.root):
            lab.capture_inventory(cfg, self.config_path, self.output_root, runner=runner)
        self.assertEqual(cfg.profile_revision, 1)
        persisted = json.loads(self.config_path.read_text())
        self.assertEqual(persisted["profile_revision"], 1)
        self.assertIn("benchmark.py", " ".join(runner.commands[0][0]))

    def test_inventory_failure_does_not_advance_revision(self):
        cfg = lab.LabConfig(node_id="lab-12345678")
        runner = FakeRunner(fail=True)
        with patch.object(lab, "REPO_ROOT", self.root):
            with self.assertRaises(subprocess.CalledProcessError):
                lab.capture_inventory(cfg, self.config_path, self.output_root, runner=runner)
        self.assertEqual(cfg.profile_revision, 0)
        self.assertFalse(self.config_path.exists())

    def test_network_client_uses_current_profile_revision(self):
        cfg = lab.LabConfig(node_id="lab-12345678", profile_revision=7)
        runner = FakeRunner()
        with patch.object(lab, "REPO_ROOT", self.root):
            lab.network_client(cfg, "192.168.1.50", 43191, self.output_root, runner=runner)
        command = runner.commands[0][0]
        self.assertIn("--profile-revision", command)
        self.assertEqual(command[command.index("--profile-revision") + 1], "7")
        self.assertEqual(command[command.index("--host") + 1], "192.168.1.50")

    def test_llama_paths_are_remembered_only_after_success(self):
        cfg = lab.LabConfig(node_id="lab-12345678", profile_revision=2)
        exe = self.root / "llama-bench.exe"
        model = self.root / "model.gguf"
        exe.touch(); model.touch()
        runner = FakeRunner()
        with patch.object(lab, "REPO_ROOT", self.root):
            lab.llama_benchmark(cfg, self.config_path, str(exe), str(model), self.output_root, runner=runner)
        persisted = json.loads(self.config_path.read_text())
        self.assertEqual(Path(persisted["llama_bench"]), exe.resolve())
        self.assertEqual(Path(persisted["model_path"]), model.resolve())

    def test_status_output_can_expose_local_remembered_paths(self):
        cfg = lab.LabConfig(node_id="lab-12345678", profile_revision=2, llama_bench="C:/tools/llama-bench.exe", model_path="D:/models/a.gguf")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            lab.emit_result("status", cfg)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["llama_bench"], cfg.llama_bench)
        self.assertEqual(data["model_path"], cfg.model_path)

    def test_run_tests_includes_all_current_suites(self):
        runner = FakeRunner()
        with patch.object(lab, "REPO_ROOT", self.root):
            lab.run_tests(runner=runner)
        self.assertEqual(len(runner.commands), 6)
        commands = [" ".join(cmd) for cmd, _, _ in runner.commands]
        for suite in (
            "tools/benchmark/tests",
            "services/orchestrator/tests",
            "protocol/tests",
            "services/identity/tests",
            "runtime/llama/tests",
            "setup/tests",
        ):
            self.assertTrue(any(suite in command for command in commands), suite)


if __name__ == "__main__":
    unittest.main()
