# SPDX-License-Identifier: Apache-2.0
"""Unit and Integration Tests for Expanded MCP Subsystem & Tools."""

from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from services.mcp.builtin.audio_tools import synthesize_speech_audio, transcribe_audio_data
from services.mcp.builtin.data_table_tools import analyze_data_table
from services.mcp.builtin.document_reader import extract_document_content
from services.mcp.builtin.file_system_tools import list_workspace_files, read_workspace_file
from services.mcp.builtin.system_tools import execute_gpu_telemetry, execute_process_summary, execute_system_info
from services.mcp.mcp_http_client import MCPHttpClient
from services.mcp.tool_registry import ToolRegistry
from services.mcp.agent_loop import AgentLoop, detect_direct_tool_intent, format_tool_content_if_json


class TestMCPExtendedCapabilities(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()

    def test_system_info_and_gpu_telemetry(self) -> None:
        sys_info = execute_system_info()
        self.assertIn("os", sys_info)
        self.assertIn("cpu_count", sys_info)
        self.assertIn("python_version", sys_info)

        gpu_info = execute_gpu_telemetry()
        self.assertIn("gpu_count", gpu_info)
        self.assertIn("devices", gpu_info)
        self.assertIn("status", gpu_info)

        proc_info = execute_process_summary()
        self.assertIn("pid", proc_info)
        self.assertIn("computemesh_services", proc_info)

    def test_safe_filesystem_tools(self) -> None:
        listing = list_workspace_files(relative_path=".", max_depth=2)
        self.assertEqual(listing.get("status"), "success")
        self.assertIn("entries", listing)
        self.assertTrue(len(listing["entries"]) > 0)

        # Path traversal guard test
        traversal = list_workspace_files(relative_path="../../../../../../../etc")
        self.assertIn("error", traversal)

        # Read workspace file test (read existing file in workspace root)
        sample_file = "requirements.txt" if os.path.exists("requirements.txt") else ("README.md" if os.path.exists("README.md") else "pyproject.toml")
        file_res = read_workspace_file(relative_path=sample_file, max_lines=20)
        self.assertEqual(file_res.get("status"), "success")
        self.assertIn("content", file_res)
        self.assertTrue(len(file_res["content"]) > 0)

    def test_data_table_analysis(self) -> None:
        csv_data = """name,age,salary,department
Alice,30,75000,Engineering
Bob,45,95000,Engineering
Charlie,25,50000,Marketing
Diana,35,80000,Sales"""
        res = analyze_data_table(csv_data)
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res["total_rows"], 4)
        self.assertEqual(res["total_columns"], 4)
        self.assertIn("salary", res["column_summaries"])
        sal_stat = res["column_summaries"]["salary"]
        self.assertEqual(sal_stat["type"], "numeric")
        self.assertEqual(sal_stat["min"], 50000)
        self.assertEqual(sal_stat["max"], 95000)
        self.assertEqual(sal_stat["mean"], 75000)

        # JSON array dataset analysis
        json_data = json.dumps([
            {"product": "Laptop", "price": 1200, "in_stock": True},
            {"product": "Mouse", "price": 25, "in_stock": True},
            {"product": "Monitor", "price": 300, "in_stock": False},
        ])
        j_res = analyze_data_table(json_data)
        self.assertEqual(j_res.get("status"), "success")
        self.assertEqual(j_res["total_rows"], 3)
        self.assertIn("price", j_res["column_summaries"])

    def test_document_content_extractor(self) -> None:
        doc_text = """# Project Overview
ComputeMesh is a decentralized AI inference network.

## Key Features
- Ultra-fast local GPU inference
- Autonomous MCP tool calling
- Deep multilingual research

## Architecture
Built with Python, C++, and Kotlin.
"""
        res = extract_document_content(doc_text)
        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res["total_sections"], 3)
        self.assertTrue(len(res["key_bullets"]) >= 3)
        self.assertEqual(res["sections"][0]["heading"], "Project Overview")

    def test_audio_tools(self) -> None:
        trans_res = transcribe_audio_data("data:audio/wav;base64,UklGRi...")
        self.assertEqual(trans_res.get("status"), "success")
        self.assertIn("transcript", trans_res)
        self.assertIn("segments", trans_res)

        synth_res = synthesize_speech_audio("Hallo ComputeMesh", speed=1.2)
        self.assertEqual(synth_res.get("status"), "success")
        self.assertEqual(synth_res["speed"], 1.2)
        self.assertEqual(synth_res["format"], "audio/wav")

    def test_mcp_http_client(self) -> None:
        client = MCPHttpClient(
            name="test_remote",
            url="http://127.0.0.1:9999/mcp",
            headers={"Authorization": "Bearer test-key"},
        )

        # Mock initialize
        mock_init_resp = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2026-07-28",
                "capabilities": {"tools": {}},
            },
        }).encode("utf-8")

        mock_tools_resp = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": "fetch_data", "description": "Remote data fetcher", "inputSchema": {"type": "object"}},
                ],
            },
        }).encode("utf-8")

        mock_call_resp = json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"status": "ok", "value": 42},
        }).encode("utf-8")

        with patch("urllib.request.urlopen") as mock_open:
            # 1. Initialize
            mock_open.return_value.__enter__.return_value.read.return_value = mock_init_resp
            self.assertTrue(client.initialize())

            # 2. List tools
            mock_open.return_value.__enter__.return_value.read.return_value = mock_tools_resp
            tools = client.list_tools()
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0]["name"], "fetch_data")

            # 3. Call tool
            mock_open.return_value.__enter__.return_value.read.return_value = mock_call_resp
            call_res = client.call_tool("fetch_data", {"query": "test"})
            self.assertEqual(call_res, {"status": "ok", "value": 42})

    def test_tool_registry_and_aliases(self) -> None:
        self.assertIsNotNone(self.registry.get_tool("get_gpu_telemetry"))
        self.assertIsNotNone(self.registry.get_tool("list_workspace_files"))
        self.assertIsNotNone(self.registry.get_tool("read_workspace_file"))
        self.assertIsNotNone(self.registry.get_tool("analyze_data_table"))
        self.assertIsNotNone(self.registry.get_tool("extract_document_content"))
        self.assertIsNotNone(self.registry.get_tool("transcribe_audio_data"))
        self.assertIsNotNone(self.registry.get_tool("synthesize_speech_audio"))

        # Test aliases
        self.assertEqual(self.registry._resolve_tool_name("gpu"), "get_gpu_telemetry")
        self.assertEqual(self.registry._resolve_tool_name("vram"), "get_gpu_telemetry")
        self.assertEqual(self.registry._resolve_tool_name("system_status"), "get_system_info")
        self.assertEqual(self.registry._resolve_tool_name("list_files"), "list_workspace_files")
        self.assertEqual(self.registry._resolve_tool_name("read_file"), "read_workspace_file")
        self.assertEqual(self.registry._resolve_tool_name("analyze_table"), "analyze_data_table")

    def test_direct_intent_detection(self) -> None:
        intent_gpu = detect_direct_tool_intent("wie ist die aktuelle gpu auslastung und vram", self.registry)
        self.assertIsNotNone(intent_gpu)
        self.assertEqual(intent_gpu[0], "get_gpu_telemetry")

        intent_sys = detect_direct_tool_intent("zeige mir den system status", self.registry)
        self.assertIsNotNone(intent_sys)
        self.assertEqual(intent_sys[0], "get_system_info")

        intent_files = detect_direct_tool_intent("zeige alle dateien im ordner", self.registry)
        self.assertIsNotNone(intent_files)
        self.assertEqual(intent_files[0], "list_workspace_files")

    def test_format_tool_content_if_json(self) -> None:
        gpu_json = json.dumps({
            "gpu_count": 1,
            "devices": [{
                "name": "NVIDIA RTX 3080",
                "vram_total_mb": 16384,
                "vram_used_mb": 4096,
                "vram_free_mb": 12288,
                "vram_usage_percent": 25.0,
                "compute_utilization_percent": 15,
                "temperature_celsius": 48.0,
            }],
        })
        formatted_gpu = format_tool_content_if_json(gpu_json)
        self.assertIn("NVIDIA RTX 3080", formatted_gpu)
        self.assertIn("12,288 MB frei", formatted_gpu)
        self.assertIn("48.0 °C", formatted_gpu)


if __name__ == "__main__":
    unittest.main()
