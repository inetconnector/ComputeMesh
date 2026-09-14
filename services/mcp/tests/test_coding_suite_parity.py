# SPDX-License-Identifier: Apache-2.0
"""Comprehensive Test Suite for High-End Coding Tools and OpenAI Parity Suite."""

import os
import shutil
import tempfile
import unittest
from typing import Any, Dict

from services.mcp.builtin.code_patch_engine import replace_file_content, multi_replace_file_content
from services.mcp.builtin.code_search_indexer import grep_search_code, extract_code_symbols
from services.mcp.builtin.code_lint_and_syntax import validate_code_syntax, check_code_quality
from services.mcp.builtin.test_runner_tools import run_project_tests
from services.mcp.builtin.git_tools import get_git_status, get_git_diff, get_git_log
from services.mcp.tool_registry import ToolRegistry
from services.mcp.agent_loop import detect_direct_tool_intent, format_tool_content_if_json
from services.mcp.config import get_mcp_config


class TestCodePatchEngine(unittest.TestCase):
    """Test Suite for Code Patch Engine."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "sample.py")
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write(
                "def calculate_total(items):\n"
                "    total = 0\n"
                "    for item in items:\n"
                "        total += item.price\n"
                "    return total\n\n"
                "def print_receipt(total):\n"
                "    print(f'Total: {total}')\n"
            )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_single_block_replacement(self):
        res = replace_file_content(
            file_path=self.test_file,
            target_content="total += item.price",
            replacement_content="total += item.price * (1.0 + item.tax_rate)",
            start_line=1,
            end_line=6,
        )
        self.assertTrue(res.get("success"))
        self.assertIn("diff", res)
        with open(self.test_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("item.tax_rate", content)

    def test_multi_chunk_replacement(self):
        chunks = [
            {
                "target_content": "total = 0",
                "replacement_content": "total = 0.0",
                "start_line": 1,
                "end_line": 3,
            },
            {
                "target_content": "print(f'Total: {total}')",
                "replacement_content": "print(f'Final Total (EUR): {total:.2f}')",
                "start_line": 6,
                "end_line": 9,
            },
        ]
        res = multi_replace_file_content(file_path=self.test_file, replacement_chunks=chunks)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("chunks_applied"), 2)
        with open(self.test_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("total = 0.0", content)
        self.assertIn("Final Total (EUR)", content)

    def test_target_not_found(self):
        res = replace_file_content(
            file_path=self.test_file,
            target_content="non_existent_function()",
            replacement_content="something_else()",
        )
        self.assertFalse(res.get("success"))
        self.assertIn("error", res)


class TestCodeSearchIndexer(unittest.TestCase):
    """Test Suite for Code Search and AST Symbol Extraction."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.py_file = os.path.join(self.temp_dir, "service.py")
        self.go_file = os.path.join(self.temp_dir, "node.go")

        with open(self.py_file, "w", encoding="utf-8") as f:
            f.write(
                "class ClusterManager:\n"
                "    \"\"\"Manages edge nodes.\"\"\"\n"
                "    def __init__(self):\n"
                "        self.nodes = []\n\n"
                "    async def register_node(self, node_id: str):\n"
                "        self.nodes.append(node_id)\n\n"
                "def helper_func():\n"
                "    return True\n"
            )

        with open(self.go_file, "w", encoding="utf-8") as f:
            f.write(
                "package main\n\n"
                "type MeshNode struct {\n"
                "    ID string\n"
                "}\n\n"
                "func (m *MeshNode) Start() error {\n"
                "    return nil\n"
                "}\n\n"
                "func NewMeshNode(id string) *MeshNode {\n"
                "    return &MeshNode{ID: id}\n"
                "}\n"
            )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_grep_search_code(self):
        res = grep_search_code(query="register_node", search_path=self.temp_dir)
        self.assertEqual(res.get("total_matches"), 1)
        self.assertEqual(res["matches"][0]["line_number"], 6)

    def test_extract_python_symbols(self):
        res = extract_code_symbols(self.py_file)
        self.assertEqual(res.get("language"), "py")
        syms = res.get("symbols", [])
        names = [s["name"] for s in syms]
        self.assertIn("ClusterManager", names)
        self.assertIn("helper_func", names)

    def test_extract_go_symbols(self):
        res = extract_code_symbols(self.go_file)
        self.assertEqual(res.get("language"), "go")
        syms = res.get("symbols", [])
        names = [s["name"] for s in syms]
        self.assertIn("MeshNode", names)
        self.assertIn("Start", names)
        self.assertIn("NewMeshNode", names)


class TestCodeLintAndSyntax(unittest.TestCase):
    """Test Suite for AST Syntax Validation and Quality Analyzer."""

    def test_valid_python_syntax(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        res = validate_code_syntax(code, language="python")
        self.assertTrue(res.get("valid"))
        self.assertEqual(res.get("total_errors"), 0)

    def test_invalid_python_syntax(self):
        code = "def broken_func(:\n    return 42\n"
        res = validate_code_syntax(code, language="python")
        self.assertFalse(res.get("valid"))
        self.assertGreaterEqual(res.get("total_errors"), 1)
        self.assertEqual(res["errors"][0]["line"], 1)

    def test_json_syntax(self):
        valid_json = '{"name": "computemesh", "active": true}'
        invalid_json = '{"name": "computemesh", active: true,}'
        self.assertTrue(validate_code_syntax(valid_json, "json")["valid"])
        self.assertFalse(validate_code_syntax(invalid_json, "json")["valid"])

    def test_code_quality_long_function(self):
        long_func = "def big_monolith():\n" + ("    x = 1\n" * 70)
        res = check_code_quality(long_func, language="python")
        warnings = [w["type"] for w in res.get("warnings", [])]
        self.assertIn("long_function", warnings)


class TestTestRunnerAndGit(unittest.TestCase):
    """Test Suite for Test Runner and Git Tools."""

    def test_test_runner_unsupported_framework(self):
        res = run_project_tests(framework="unsupported_xyz")
        self.assertFalse(res.get("success"))
        self.assertIn("error", res)

    def test_git_status_and_log(self):
        status = get_git_status()
        self.assertTrue(status.get("is_git_repo"))
        self.assertTrue(bool(status.get("branch")))

        log_res = get_git_log(max_count=3)
        self.assertGreaterEqual(log_res.get("total_commits_fetched", 0), 1)

        diff_res = get_git_diff()
        self.assertIn("has_changes", diff_res)


class TestRegistryAndAgentLoopCodingParity(unittest.TestCase):
    """Test Suite for Tool Registry & AgentLoop Parity."""

    def test_tools_registered_in_openai_format(self):
        reg = ToolRegistry(get_mcp_config())
        tools = reg.get_openai_tools()
        names = [t["function"]["name"] for t in tools]

        self.assertIn("replace_file_content", names)
        self.assertIn("multi_replace_file_content", names)
        self.assertIn("grep_search_code", names)
        self.assertIn("extract_code_symbols", names)
        self.assertIn("validate_code_syntax", names)
        self.assertIn("run_project_tests", names)
        self.assertIn("get_git_status", names)
        self.assertIn("get_git_diff", names)
        self.assertIn("get_git_log", names)

    def test_direct_intent_coding(self):
        intent_status = detect_direct_tool_intent("zeige git status")
        self.assertIsNotNone(intent_status)
        self.assertEqual(intent_status[0], "get_git_status")

        intent_diff = detect_direct_tool_intent("zeige git diff")
        self.assertIsNotNone(intent_diff)
        self.assertEqual(intent_diff[0], "get_git_diff")

        intent_grep = detect_direct_tool_intent("suche im code nach register_node")
        self.assertIsNotNone(intent_grep)
        self.assertEqual(intent_grep[0], "grep_search_code")
        self.assertEqual(intent_grep[1]["query"], "register_node")

        intent_sym = detect_direct_tool_intent("zeige symbole in service.py")
        self.assertIsNotNone(intent_sym)
        self.assertEqual(intent_sym[0], "extract_code_symbols")

        intent_test = detect_direct_tool_intent("starte tests")
        self.assertIsNotNone(intent_test)
        self.assertEqual(intent_test[0], "run_project_tests")

    def test_formatted_markdown_coding_output(self):
        grep_json = '{"query": "node", "total_matches": 1, "matches": [{"file": "src/node.go", "line_number": 4, "line_content": "type MeshNode struct"}]}'
        fmt_grep = format_tool_content_if_json(grep_json)
        self.assertIn("Code-Suchergebnisse", fmt_grep)
        self.assertIn("src/node.go:4", fmt_grep)

        diff_json = '{"file_path": "server.py", "replacements_count": 1, "diff": "- old_code\\n+ new_code"}'
        fmt_diff = format_tool_content_if_json(diff_json)
        self.assertIn("Code erfolgreich angepasst", fmt_diff)
        self.assertIn("```diff", fmt_diff)


if __name__ == "__main__":
    unittest.main()
