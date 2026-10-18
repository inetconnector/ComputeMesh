"""Infrastructure-only tests: no model, hardware or production PASS is implied."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "ai_capability_baseline.py"
SUITE = HERE / "ai_capability_tasks_v1.json"


def invoke(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


class CapabilityBaselineTests(unittest.TestCase):
    def test_suite_covers_required_categories_tiers_and_languages(self) -> None:
        data = json.loads(SUITE.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual({x["tier"] for x in data["tasks"]}, {"basic", "intermediate", "advanced"})
        self.assertEqual({x["locale"] for x in data["tasks"]}, {"de", "en"})
        self.assertEqual(len({x["id"] for x in data["tasks"]}), len(data["tasks"]))
        self.assertGreaterEqual(len(data["tasks"]), 22)

    def test_empty_evidence_remains_unmeasured_and_blocks_release(self) -> None:
        result = invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["passed"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["not_measured"], summary["task_count"])
        self.assertEqual(summary["release_gate"], "BLOCKED")
        self.assertIsNone(summary["numeric_slos"])
        strict = invoke("--require-complete")
        self.assertEqual(strict.returncode, 2, strict.stderr)

    def test_evidence_required_for_any_claimed_pass_or_fail(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "observations.jsonl"
            path.write_text(json.dumps({"task_id": "AC-001", "status": "passed"}) + "\n",
                            encoding="utf-8")
            bad = invoke("--observations", str(path))
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("missing", bad.stderr)
            path.write_text(json.dumps({
                "task_id": "AC-001", "status": "failed", "model_id": "fixture-model",
                "config_id": "fixture-v1", "evidence_ref": "fixture://failed-1",
                "review_rationale": "Expected citation was absent", "latency_ms": 12.5,
            }) + "\n", encoding="utf-8")
            good = invoke("--observations", str(path))
            self.assertEqual(good.returncode, 0, good.stderr)
            summary = json.loads(good.stdout)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["passed"], 0)
            self.assertEqual(summary["not_measured"], summary["task_count"] - 1)

    def test_duplicate_or_unknown_task_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "observations.jsonl"
            item = json.dumps({"task_id": "AC-001", "status": "not_measured"})
            path.write_text(item + "\n" + item + "\n", encoding="utf-8")
            self.assertNotEqual(invoke("--observations", str(path)).returncode, 0)
            path.write_text(json.dumps({"task_id": "not-a-task", "status": "not_measured"}) + "\n",
                            encoding="utf-8")
            self.assertNotEqual(invoke("--observations", str(path)).returncode, 0)

    def test_report_written_without_secret_or_prompt_body(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "report.json"
            result = invoke("--output", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = path.read_text(encoding="utf-8")
            report = json.loads(data)
            self.assertNotIn("prompt", report)
            self.assertNotIn("api_key", report)
            self.assertNotIn("evidence_ref", report)
            self.assertEqual(report["task_count"], 22)


if __name__ == "__main__":
    unittest.main()
