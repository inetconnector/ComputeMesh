# SPDX-License-Identifier: Apache-2.0
"""Comprehensive Unit & Mock Test Suite for LocalCode Parity Tools."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from services.mcp.builtin.workspace_quarantine import (
    quarantine_stage_files,
    quarantine_validate,
    quarantine_commit,
    quarantine_rollback,
)
from services.mcp.builtin.workspace_doctor import run_doctor_diagnostics
from services.mcp.builtin.mission_journal import (
    mission_start,
    mission_log_step,
    mission_verify_postconditions,
    mission_get_summary,
)
from services.mcp.builtin.tool_installer import detect_missing_tools, install_dev_tool
from services.mcp.builtin.adb_bridge_tools import (
    adb_list_devices,
    adb_capture_screenshot,
    adb_install_app,
    adb_get_system_log,
)
from services.mcp.tool_registry import ToolRegistry
from services.mcp.agent_loop import detect_direct_tool_intent, format_tool_content_if_json


class TestWorkspaceQuarantine(unittest.TestCase):
    """Test Suite for Workspace Quarantine and Shadow Staging."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sample_file = os.path.join(self.temp_dir, "app.py")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write("def hello():\n    return 'Hello World'\n")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stage_and_validate_and_commit(self):
        new_code = "def hello():\n    return 'Hello ComputeMesh Quarantined'\n"
        stage_res = quarantine_stage_files(
            files={"app.py": new_code},
            workspace_root=self.temp_dir,
        )
        self.assertTrue(stage_res.get("success"))
        txn_id = stage_res.get("txn_id")
        self.assertIn("app.py", stage_res.get("diffs", {}))

        # Validate syntax
        val_res = quarantine_validate(txn_id=txn_id, workspace_root=self.temp_dir)
        self.assertTrue(val_res.get("success"))
        self.assertTrue(val_res.get("valid"))

        # Commit
        commit_res = quarantine_commit(txn_id=txn_id, workspace_root=self.temp_dir)
        self.assertTrue(commit_res.get("success"))
        self.assertEqual(commit_res.get("total_committed"), 1)

        with open(self.sample_file, "r", encoding="utf-8") as f:
            updated = f.read()
        self.assertIn("ComputeMesh Quarantined", updated)

    def test_stage_syntax_error_and_rollback(self):
        broken_code = "def hello(\n    broken syntax! %%"
        stage_res = quarantine_stage_files(
            files={"broken.py": broken_code},
            workspace_root=self.temp_dir,
        )
        txn_id = stage_res.get("txn_id")

        val_res = quarantine_validate(txn_id=txn_id, workspace_root=self.temp_dir)
        self.assertFalse(val_res.get("valid"))
        self.assertGreaterEqual(val_res.get("total_errors"), 1)

        rb_res = quarantine_rollback(txn_id=txn_id, workspace_root=self.temp_dir)
        self.assertTrue(rb_res.get("success"))
        self.assertEqual(rb_res.get("status"), "rolled_back")


class TestWorkspaceDoctor(unittest.TestCase):
    """Test Suite for Workspace & System Doctor."""

    def test_run_doctor_diagnostics(self):
        res = run_doctor_diagnostics()
        self.assertTrue(res.get("success"))
        self.assertIn(res.get("overall_status"), ("healthy", "warning", "error"))
        self.assertGreater(res.get("total_checks", 0), 3)
        names = [it.get("name") for it in res.get("items", [])]
        self.assertIn("Python", names)
        self.assertIn("Git", names)


class TestMissionJournal(unittest.TestCase):
    """Test Suite for Mission Journal & Lifecycle Checkpoints."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_mission_lifecycle(self):
        # 1. Start mission
        start_res = mission_start(
            objective="Build High-End LocalCode Agent Parity",
            constraints=["Preserve single responsibility", "100% test pass rate"],
            success_criteria=["Quarantine working", "Doctor working"],
            workspace_root=self.temp_dir,
        )
        self.assertTrue(start_res.get("success"))
        m_id = start_res.get("mission_id")

        # 2. Log steps
        step_res = mission_log_step(
            mission_id=m_id,
            phase="staging",
            action="Staged quarantine modules",
            evidence="2 files created",
            workspace_root=self.temp_dir,
        )
        self.assertTrue(step_res.get("success"))
        self.assertEqual(step_res.get("step_index"), 2)

        # 3. Verify postconditions
        verify_res = mission_verify_postconditions(
            mission_id=m_id,
            checks=[
                {"name": "Quarantine working", "passed": True},
                {"name": "Doctor working", "passed": True},
            ],
            workspace_root=self.temp_dir,
        )
        self.assertTrue(verify_res.get("success"))
        self.assertTrue(verify_res.get("all_passed"))

        # 4. Summary
        summary = mission_get_summary(mission_id=m_id, workspace_root=self.temp_dir)
        self.assertTrue(summary.get("success"))
        self.assertEqual(summary.get("mission", {}).get("status"), "completed")


class TestToolInstaller(unittest.TestCase):
    """Test Suite for Tool Scanner and Installer."""

    def test_detect_missing_tools(self):
        res = detect_missing_tools(["python", "non_existent_fake_tool_xyz_123"])
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("total_scanned"), 2)
        self.assertEqual(res.get("installed_count"), 1)
        self.assertEqual(res.get("missing_count"), 1)
        self.assertEqual(res.get("missing")[0]["name"], "non_existent_fake_tool_xyz_123")

    @patch("subprocess.run")
    def test_install_dev_tool(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Successfully installed pytest-8.0.0"
        mock_run.return_value = mock_proc

        res = install_dev_tool("pytest", package_manager="pip")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("tool_name"), "pytest")


class TestADBBridge(unittest.TestCase):
    """Test Suite for Android ADB Bridge Tools."""

    @patch("subprocess.run")
    def test_adb_list_devices(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = (
            "List of devices attached\n"
            "emulator-5554          device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64 device:emulator64_x86_64\n"
            "RFCY21GXM9E            device product:e3sxeea model:SM_S928B device:e3s\n"
        )
        mock_run.return_value = mock_proc

        res = adb_list_devices()
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("total_devices"), 2)
        self.assertTrue(res.get("devices")[0]["is_emulator"])
        self.assertFalse(res.get("devices")[1]["is_emulator"])

    @patch("subprocess.run")
    def test_adb_get_system_log(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "09-14 20:00:00.123 1000 1000 I ComputeMesh: Node connected\n"
        mock_run.return_value = mock_proc

        res = adb_get_system_log(lines=10)
        self.assertTrue(res.get("success"))
        self.assertIn("ComputeMesh: Node connected", res.get("log"))


class TestRegistryAndAgentLoopLocalCodeIntegration(unittest.TestCase):
    """Test Suite for Tool Registry & Agent Loop LocalCode Integration."""

    def setUp(self):
        self.registry = ToolRegistry()

    def test_localcode_tools_registered(self):
        tools = [t.name for t in self.registry.list_tools()]
        expected = [
            "run_doctor_diagnostics",
            "quarantine_stage_files",
            "quarantine_validate",
            "quarantine_commit",
            "quarantine_rollback",
            "mission_start",
            "mission_log_step",
            "mission_verify_postconditions",
            "mission_get_summary",
            "detect_missing_tools",
            "install_dev_tool",
            "adb_list_devices",
            "adb_capture_screenshot",
            "adb_install_app",
            "adb_get_system_log",
        ]
        for name in expected:
            self.assertIn(name, tools, f"Missing registration for: {name}")

    def test_aliases(self):
        self.assertEqual(self.registry.get_tool("doctor").name, "run_doctor_diagnostics")
        self.assertEqual(self.registry.get_tool("quarantine").name, "quarantine_stage_files")
        self.assertEqual(self.registry.get_tool("mission").name, "mission_start")
        self.assertEqual(self.registry.get_tool("check_tools").name, "detect_missing_tools")
        self.assertEqual(self.registry.get_tool("adb").name, "adb_list_devices")

    def test_intent_detection(self):
        intent_doc = detect_direct_tool_intent("doctor", self.registry)
        self.assertIsNotNone(intent_doc)
        self.assertEqual(intent_doc[0], "run_doctor_diagnostics")

        intent_adb = detect_direct_tool_intent("adb devices", self.registry)
        self.assertIsNotNone(intent_adb)
        self.assertEqual(intent_adb[0], "adb_list_devices")

        intent_miss = detect_direct_tool_intent("starte mission: Full Audit", self.registry)
        self.assertIsNotNone(intent_miss)
        self.assertEqual(intent_miss[0], "mission_start")
        self.assertEqual(intent_miss[1].get("objective"), "Full Audit")

    def test_format_tool_content_if_json(self):
        # Doctor formatting
        doc_json = json.dumps({
            "overall_status": "healthy",
            "total_checks": 2,
            "items": [
                {"name": "Python", "status": "healthy", "summary": "Python 3.11.9", "remediation": ""},
                {"name": "Git", "status": "healthy", "summary": "git version 2.45", "remediation": ""},
            ],
        })
        doc_md = format_tool_content_if_json(doc_json)
        self.assertIn("### 🩺 Workspace & System Doctor Diagnosereport: 🟢 **HEALTHY**", doc_md)
        self.assertIn("Python", doc_md)


if __name__ == "__main__":
    unittest.main()
