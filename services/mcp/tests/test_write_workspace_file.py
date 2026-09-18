# SPDX-License-Identifier: Apache-2.0
"""Unit and regression tests for write_workspace_file MCP tool."""

import os
import tempfile
import unittest
from pathlib import Path

from services.mcp.builtin.file_system_tools import write_workspace_file, read_workspace_file, _get_safe_workspace_root
from services.mcp.tool_registry import ToolRegistry


class TestWriteWorkspaceFile(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.test_subpath = "temp_test_write_tool"
        self.root = _get_safe_workspace_root()
        self.target_dir = self.root / self.test_subpath
        self.target_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        # Cleanup created files in test folder
        if self.target_dir.exists():
            for f in self.target_dir.glob("**/*"):
                if f.is_file():
                    try:
                        f.unlink()
                    except Exception:
                        pass
            try:
                for d in sorted(self.target_dir.glob("**/*"), reverse=True):
                    if d.is_dir():
                        d.rmdir()
                self.target_dir.rmdir()
            except Exception:
                pass

    def test_write_and_read_new_file(self):
        rel_path = f"{self.test_subpath}/hello.txt"
        content = "Hello ComputeMesh World!\nSecond Line.\n"

        res = write_workspace_file(rel_path, content, overwrite=True, create_dirs=True)
        self.assertTrue(res.get("success"), f"Write failed: {res}")
        self.assertEqual(res.get("lines_written"), 2)

        # Read back
        read_res = read_workspace_file(rel_path)
        self.assertEqual(read_res.get("status"), "success")
        self.assertIn("Hello ComputeMesh World!", read_res.get("content", ""))

    def test_write_with_nested_auto_directory_creation(self):
        rel_path = f"{self.test_subpath}/nested/sub/deep/test_config.json"
        content = '{\n  "status": "active"\n}'

        res = write_workspace_file(rel_path, content, create_dirs=True)
        self.assertTrue(res.get("success"))
        self.assertTrue((self.root / rel_path).exists())

    def test_overwrite_protection(self):
        rel_path = f"{self.test_subpath}/locked.txt"
        write_workspace_file(rel_path, "Initial text", overwrite=True)

        # Overwrite=False should fail
        res2 = write_workspace_file(rel_path, "New text", overwrite=False)
        self.assertFalse(res2.get("success"))
        self.assertIn("existiert bereits", res2.get("error", ""))

    def test_tool_registry_execution(self):
        rel_path = f"{self.test_subpath}/registry_test.md"
        res = self.registry.execute_tool(
            "write_workspace_file",
            {"relative_path": rel_path, "content": "# Header\nBody text\n", "overwrite": True},
            is_owner=True,
        )
        self.assertTrue(res.get("success"))
        self.assertTrue((self.root / rel_path).exists())


if __name__ == "__main__":
    unittest.main()
